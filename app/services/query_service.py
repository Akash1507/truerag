import hashlib
import inspect
import json
import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from fastapi.responses import StreamingResponse

from app.core.decorators import service_method
from app.core.errors import (
    ForbiddenError,
    InvalidCursorError,
    ProviderUnavailableError,
    SessionExpiredError,
    TokenBudgetExceededError,
    TrueRAGError,
)
from app.db.dao.conversation_dao import ConversationSessionDAO, conversation_dao
from app.db.dao.query_cost_dao import QueryCostDAO, query_cost_dao
from app.models.agent import AgentDocument
from app.models.conversation import ConversationMessage
from app.models.query import QueryRequest, QueryResponse, StreamEvent
from app.models.query_cost import QueryCost
from app.models.tenant import TenantDocument
from app.pipelines.query.pipeline import (
    QueryPipelineCircuitBreakers,
    run_query_pipeline,
    stream_query_pipeline,
)
from app.providers.registry import EMBEDDING_REGISTRY
from app.services.agent_service import AgentService, agent_service
from app.services.audit_service import AuditService, audit_service
from app.services.metrics_service import MetricsService, metrics_service
from app.utils.cost_tracker import get_cost_accumulator, init_cost_tracking
from app.utils.observability import LatencyTracker, _request_id_var, get_logger, log_stage_latency
from app.utils.time import current_month_str
from app.utils import semantic_cache
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


class QueryService:
    def __init__(
        self,
        agent_service_dep: AgentService,
        audit_service_dep: AuditService,
        metrics_service_dep: MetricsService,
        query_cost_dao_dep: QueryCostDAO,
        conversation_dao_dep: ConversationSessionDAO,
    ) -> None:
        self._agent_service = agent_service_dep
        self._audit_service = audit_service_dep
        self._metrics_service = metrics_service_dep
        self._query_cost_dao = query_cost_dao_dep
        self._conversation_dao = conversation_dao_dep
        self._pipeline_breakers: dict[
            tuple[str, str, str, str],
            QueryPipelineCircuitBreakers,
        ] = {}

    @service_method("handle_query")
    async def handle_query(
        self,
        agent_id: str,
        tenant_id: str,
        api_key_hash: str,
        request: QueryRequest,
        background_tasks: BackgroundTasks,
        tenant: TenantDocument | None = None,
    ) -> QueryResponse | StreamingResponse:
        init_cost_tracking()
        agent = await self._agent_service.get_agent(agent_id, tenant_id)
        if tenant is not None and tenant.monthly_token_budget is not None:
            monthly_total = await self._query_cost_dao.get_monthly_token_total(
                tenant_id,
                current_month_str(),
            )
            if monthly_total >= tenant.monthly_token_budget:
                raise TokenBudgetExceededError()
        effective_top_k = request.top_k if request.top_k is not None else agent.top_k
        scrubbed = scrub_pii(request.query)
        query_hash = hashlib.sha256(scrubbed.encode()).hexdigest()
        request_id = _request_id_var.get()
        conversation_history: list[ConversationMessage] | None = None
        session_id = request.session_id
        if session_id is None:
            session = await self._conversation_dao.create_session(agent_id=agent_id, tenant_id=tenant_id)
            session_id = session.session_id
        else:
            session = await self._conversation_dao.get_session(
                session_id=session_id,
                agent_id=agent_id,
                tenant_id=tenant_id,
            )
            if session is None:
                raise ForbiddenError("Session does not belong to this agent or tenant")
            if session.updated_at < datetime.now(UTC) - timedelta(hours=24):
                raise SessionExpiredError()
            conversation_history = session.messages

        if request.stream:
            return await self._handle_stream_query(
                agent_id=agent_id,
                tenant_id=tenant_id,
                api_key_hash=api_key_hash,
                request=request,
                background_tasks=background_tasks,
                agent=agent,
                effective_top_k=effective_top_k,
                scrubbed_query=scrubbed,
                query_hash=query_hash,
                request_id=request_id,
                session_id=session_id,
                conversation_history=conversation_history,
            )

        response: QueryResponse | None = None
        cache_hit = False
        total_tracker = LatencyTracker()
        query_vector: list[float] | None = None
        try:
            if agent.semantic_cache_enabled and agent.semantic_cache_threshold is not None:
                embedder_cls = EMBEDDING_REGISTRY.get(agent.embedding_provider)
                if embedder_cls is None:
                    raise ProviderUnavailableError(
                        f"Embedding provider '{agent.embedding_provider}' not registered"
                    )
                embedder = embedder_cls()
                vectors = await embedder.embed([scrubbed])
                if vectors:
                    query_vector = vectors[0]
                    cache_lookup_tracker = LatencyTracker()
                    cached = await semantic_cache.lookup(
                        agent_id,
                        query_vector,
                        agent.semantic_cache_threshold,
                    )
                    log_stage_latency(
                        logger=logger,
                        operation="cache_lookup",
                        latency_ms=cache_lookup_tracker.elapsed_ms(),
                    )
                    if cached is not None:
                        cache_hit = True
                        response = QueryResponse(
                            answer=cached,
                            confidence=1.0,
                            citations=[],
                            latency_ms=total_tracker.elapsed_ms(),
                            session_id=session_id,
                        )
                        await self._conversation_dao.append_messages(
                            session_id=session_id,
                            user_msg=scrubbed,
                            assistant_msg=response.answer,
                        )
                        return response

            pipeline_kwargs: dict[str, object] = {
                "query": request.query,
                "top_k": effective_top_k,
                "agent": agent,
                "filters": request.filters,
                "output_format": request.output_format,
                "request_id": request_id,
                "conversation_history": conversation_history,
                "circuit_breakers": self._get_pipeline_breakers(agent),
            }
            if (
                query_vector is not None
                and "precomputed_query_vector" in inspect.signature(run_query_pipeline).parameters
            ):
                pipeline_kwargs["precomputed_query_vector"] = query_vector

            response = await run_query_pipeline(**pipeline_kwargs)
            response.session_id = session_id

            if (
                agent.semantic_cache_enabled
                and agent.semantic_cache_threshold is not None
                and query_vector is not None
            ):
                await semantic_cache.store(agent_id, query_vector, query_hash, response.answer)
            await self._conversation_dao.append_messages(
                session_id=session_id,
                user_msg=scrubbed,
                assistant_msg=response.answer,
            )

            accumulator = get_cost_accumulator()
            if accumulator is not None:
                try:
                    cost_entry = QueryCost.model_construct(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        request_id=request_id,
                        prompt_tokens=accumulator.prompt_tokens,
                        completion_tokens=accumulator.completion_tokens,
                        hyde_prompt_tokens=accumulator.hyde_prompt_tokens,
                        hyde_completion_tokens=accumulator.hyde_completion_tokens,
                        embedding_calls=accumulator.embedding_calls,
                        reranker_calls=accumulator.reranker_calls,
                    )
                    await self._query_cost_dao.insert_one(
                        cost_entry
                    )
                except Exception as exc:
                    logger.error(
                        "query_cost_write_failed",
                        extra={
                            "operation": "query_cost_write",
                            "extra_data": {
                                "tenant_id": tenant_id,
                                "agent_id": agent_id,
                                "request_id": request_id,
                                "error": str(exc),
                            },
                        },
                    )

            return response
        finally:
            accumulator = get_cost_accumulator()
            total_tokens = 0
            if accumulator is not None:
                total_tokens = accumulator.prompt_tokens + accumulator.completion_tokens
            self._metrics_service.record_query(
                tenant_id=tenant_id,
                agent_id=agent_id,
                latency_ms=response.latency_ms if response is not None else total_tracker.elapsed_ms(),
                total_tokens=total_tokens,
            )
            background_tasks.add_task(
                self._audit_service.write_audit_log,
                tenant_id=tenant_id,
                agent_id=agent_id,
                api_key_hash=api_key_hash,
                query_hash=query_hash,
                response_confidence=response.confidence if response is not None else 0.0,
                cache_hit=cache_hit,
            )

    async def _handle_stream_query(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        api_key_hash: str,
        request: QueryRequest,
        background_tasks: BackgroundTasks,
        agent: AgentDocument,
        effective_top_k: int,
        scrubbed_query: str,
        query_hash: str,
        request_id: str,
        session_id: str,
        conversation_history: list[ConversationMessage] | None,
    ) -> StreamingResponse:
        total_tracker = LatencyTracker()
        cache_hit = False
        query_vector: list[float] | None = None

        if agent.semantic_cache_enabled and agent.semantic_cache_threshold is not None:
            embedder_cls = EMBEDDING_REGISTRY.get(agent.embedding_provider)
            if embedder_cls is None:
                raise ProviderUnavailableError(
                    f"Embedding provider '{agent.embedding_provider}' not registered"
                )
            embedder = embedder_cls()
            vectors = await embedder.embed([scrubbed_query])
            if vectors:
                query_vector = vectors[0]
                cache_lookup_tracker = LatencyTracker()
                cached = await semantic_cache.lookup(
                    agent_id,
                    query_vector,
                    agent.semantic_cache_threshold,
                )
                log_stage_latency(
                    logger=logger,
                    operation="cache_lookup",
                    latency_ms=cache_lookup_tracker.elapsed_ms(),
                )
                if cached is not None:
                    cache_hit = True
                    base_stream = self._stream_cached_response(cached)
                else:
                    base_stream = stream_query_pipeline(
                        query=request.query,
                        top_k=effective_top_k,
                        agent=agent,
                        filters=request.filters,
                        request_id=request_id,
                        output_format=request.output_format,
                        conversation_history=conversation_history,
                        circuit_breakers=self._get_pipeline_breakers(agent),
                    )
            else:
                base_stream = stream_query_pipeline(
                    query=request.query,
                    top_k=effective_top_k,
                    agent=agent,
                    filters=request.filters,
                    request_id=request_id,
                    output_format=request.output_format,
                    conversation_history=conversation_history,
                    circuit_breakers=self._get_pipeline_breakers(agent),
                )
        else:
            base_stream = stream_query_pipeline(
                query=request.query,
                top_k=effective_top_k,
                agent=agent,
                filters=request.filters,
                request_id=request_id,
                output_format=request.output_format,
                conversation_history=conversation_history,
                circuit_breakers=self._get_pipeline_breakers(agent),
            )

        async def wrapped_stream() -> AsyncGenerator[str, None]:
            response_confidence = 0.0
            answer_parts: list[str] = []
            try:
                async for chunk in base_stream:
                    parsed = self._parse_sse_payload(chunk)
                    if isinstance(parsed, dict):
                        event_type = parsed.get("type")
                        if event_type == "token" and isinstance(parsed.get("token"), str):
                            answer_parts.append(parsed["token"])
                        elif event_type == "done" and isinstance(parsed.get("confidence"), (int, float)):
                            response_confidence = float(parsed["confidence"])
                            parsed["session_id"] = session_id
                            yield f"data: {json.dumps(parsed)}\n\n"
                            continue
                    yield chunk
            finally:
                full_answer = " ".join(answer_parts) if cache_hit else "".join(answer_parts)
                if (
                    not cache_hit
                    and agent.semantic_cache_enabled
                    and agent.semantic_cache_threshold is not None
                    and query_vector is not None
                    and answer_parts
                ):
                    await semantic_cache.store(agent_id, query_vector, query_hash, full_answer)
                if answer_parts:
                    await self._conversation_dao.append_messages(
                        session_id=session_id,
                        user_msg=scrubbed_query,
                        assistant_msg=full_answer,
                    )

                accumulator = get_cost_accumulator()
                if accumulator is not None:
                    try:
                        cost_entry = QueryCost.model_construct(
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                            request_id=request_id,
                            prompt_tokens=accumulator.prompt_tokens,
                            completion_tokens=accumulator.completion_tokens,
                            hyde_prompt_tokens=accumulator.hyde_prompt_tokens,
                            hyde_completion_tokens=accumulator.hyde_completion_tokens,
                            embedding_calls=accumulator.embedding_calls,
                            reranker_calls=accumulator.reranker_calls,
                        )
                        await self._query_cost_dao.insert_one(cost_entry)
                    except Exception as exc:
                        logger.error(
                            "query_cost_write_failed",
                            extra={
                                "operation": "query_cost_write",
                                "extra_data": {
                                    "tenant_id": tenant_id,
                                    "agent_id": agent_id,
                                    "request_id": request_id,
                                    "error": str(exc),
                                },
                            },
                        )

                total_tokens = 0
                if accumulator is not None:
                    total_tokens = accumulator.prompt_tokens + accumulator.completion_tokens
                self._metrics_service.record_query(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    latency_ms=total_tracker.elapsed_ms(),
                    total_tokens=total_tokens,
                )
                background_tasks.add_task(
                    self._audit_service.write_audit_log,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    api_key_hash=api_key_hash,
                    query_hash=query_hash,
                    response_confidence=response_confidence,
                    cache_hit=cache_hit,
                )

        return StreamingResponse(
            content=wrapped_stream(),
            media_type="text/event-stream",
            background=background_tasks,
        )

    def _get_pipeline_breakers(self, agent: AgentDocument) -> QueryPipelineCircuitBreakers:
        key = (
            agent.llm_provider,
            agent.embedding_provider,
            agent.vector_store,
            agent.reranker,
        )
        existing = self._pipeline_breakers.get(key)
        if existing is not None:
            return existing
        created = QueryPipelineCircuitBreakers()
        self._pipeline_breakers[key] = created
        return created

    @staticmethod
    async def _stream_cached_response(answer: str) -> AsyncGenerator[str, None]:
        chunks = QueryService._chunk_text(answer, words_per_chunk=10)
        stream_tracker = LatencyTracker()
        for chunk in chunks:
            yield QueryService._stream_event_line(StreamEvent(type="token", token=chunk))
            await asyncio.sleep(0.05)
        yield QueryService._stream_event_line(
            StreamEvent(
                type="done",
                confidence=1.0,
                citations=[],
                latency_ms=stream_tracker.elapsed_ms(),
            )
        )
        yield QueryService._stream_event_line("[DONE]")

    @staticmethod
    def _stream_event_line(event: StreamEvent | str) -> str:
        if isinstance(event, str):
            return f"data: {event}\n\n"
        payload = event.model_dump(mode="json", exclude_none=True)
        return f"data: {json.dumps(payload)}\n\n"

    @staticmethod
    def _chunk_text(text: str, words_per_chunk: int) -> list[str]:
        words = text.split()
        if not words:
            return []
        return [
            " ".join(words[index : index + words_per_chunk])
            for index in range(0, len(words), words_per_chunk)
        ]

    @staticmethod
    def _parse_sse_payload(chunk: str) -> dict[str, object] | None:
        if not chunk.startswith("data: "):
            return None
        payload = chunk[len("data: ") :].strip()
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None


query_service = QueryService(
    agent_service_dep=agent_service,
    audit_service_dep=audit_service,
    metrics_service_dep=metrics_service,
    query_cost_dao_dep=query_cost_dao,
    conversation_dao_dep=conversation_dao,
)


async def handle_query(
    agent_id: str,
    tenant_id: str,
    api_key_hash: str,
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantDocument | None = None,
) -> QueryResponse | StreamingResponse:
    return await query_service.handle_query(
        agent_id,
        tenant_id,
        api_key_hash,
        request,
        background_tasks,
        tenant=tenant,
    )
