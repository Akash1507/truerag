import hashlib
import inspect

from fastapi import BackgroundTasks

from app.db.dao.query_cost_dao import query_cost_dao
from app.core.errors import ProviderUnavailableError
from app.models.query import QueryRequest, QueryResponse
from app.models.query_cost import QueryCost
from app.pipelines.query.pipeline import run_query_pipeline
from app.providers.registry import EMBEDDING_REGISTRY
from app.services import agent_service, audit_service, metrics_service
from app.utils.cost_tracker import get_cost_accumulator, init_cost_tracking
from app.utils.observability import LatencyTracker, _request_id_var, get_logger, log_stage_latency
from app.utils import semantic_cache
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


async def handle_query(
    agent_id: str,
    tenant_id: str,
    api_key_hash: str,
    request: QueryRequest,
    background_tasks: BackgroundTasks,
) -> QueryResponse:
    init_cost_tracking()
    agent = await agent_service.get_agent(agent_id, tenant_id)
    effective_top_k = request.top_k if request.top_k is not None else agent.top_k
    scrubbed = scrub_pii(request.query)
    query_hash = hashlib.sha256(scrubbed.encode()).hexdigest()
    request_id = _request_id_var.get()

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
                    )
                    return response

        pipeline_kwargs: dict[str, object] = {
            "query": request.query,
            "top_k": effective_top_k,
            "agent": agent,
            "filters": request.filters,
            "output_format": request.output_format,
            "request_id": request_id,
        }
        # Allow forward compatibility with pipeline support for query-vector reuse.
        if (
            query_vector is not None
            and "precomputed_query_vector" in inspect.signature(run_query_pipeline).parameters
        ):
            pipeline_kwargs["precomputed_query_vector"] = query_vector

        response = await run_query_pipeline(**pipeline_kwargs)

        if (
            agent.semantic_cache_enabled
            and agent.semantic_cache_threshold is not None
            and query_vector is not None
        ):
            await semantic_cache.store(agent_id, query_vector, query_hash, response.answer)

        accumulator = get_cost_accumulator()
        if accumulator is not None:
            try:
                await query_cost_dao.insert_one(
                    QueryCost(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        request_id=request_id,
                        prompt_tokens=accumulator.prompt_tokens,
                        completion_tokens=accumulator.completion_tokens,
                        embedding_calls=accumulator.embedding_calls,
                        reranker_calls=accumulator.reranker_calls,
                    )
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
        metrics_service.record_query(
            tenant_id=tenant_id,
            agent_id=agent_id,
            latency_ms=response.latency_ms if response is not None else total_tracker.elapsed_ms(),
            total_tokens=total_tokens,
        )
        background_tasks.add_task(
            audit_service.write_audit_log,
            tenant_id=tenant_id,
            agent_id=agent_id,
            api_key_hash=api_key_hash,
            query_hash=query_hash,
            response_confidence=response.confidence if response is not None else 0.0,
            cache_hit=cache_hit,
        )
