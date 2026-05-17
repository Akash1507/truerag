import asyncio
import json
from collections.abc import AsyncGenerator
from statistics import mean
from typing import Literal

from app.core.errors import (
    CircuitOpenError,
    EmbeddingModelMismatchError,
    ProviderUnavailableError,
    ServiceUnavailableError,
)
from app.models.agent import AgentDocument
from app.models.chunk import Chunk, VectorResult
from app.models.conversation import ConversationMessage
from app.models.query import Citation, QueryResponse, StreamEvent
from app.pipelines.query.faithfulness_check import check_hallucination
from app.pipelines.query.generator import _build_prompt, generate_answer
from app.pipelines.query.rewriter import rewrite_query
from app.pipelines.query.router import route_query
from app.pipelines.query.rrf import reciprocal_rank_fusion
from app.pipelines.query.sparse_retriever import retrieve_sparse
from app.providers.registry import EMBEDDING_REGISTRY, LLM_REGISTRY, RERANKER_REGISTRY, VECTOR_STORE_REGISTRY
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.cost_tracker import get_cost_accumulator, record_hyde_usage
from app.utils.observability import LatencyTracker, get_logger, log_stage_latency
from app.utils.pii import scrub_pii

logger = get_logger(__name__)

_HYDE_PROMPT = (
    "Generate a concise passage that would appear in a document answering the following question. "
    "Write only the passage, no preamble."
)
_MULTI_QUERY_PROMPT_TEMPLATE = (
    "Generate {count} semantically diverse search queries for the following question. "
    "Return a JSON array of strings only.\n\nQuestion: {query}"
)


class QueryPipelineCircuitBreakers:
    def __init__(self) -> None:
        self._cb_llm = CircuitBreaker()
        self._cb_embed = CircuitBreaker()
        self._cb_vector = CircuitBreaker()
        self._cb_rerank = CircuitBreaker()


async def run_query_pipeline(
    query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None = None,
    output_format: Literal["text", "json"] | None = None,
    request_id: str | None = None,
    conversation_history: list[ConversationMessage] | None = None,
    circuit_breakers: QueryPipelineCircuitBreakers | None = None,
) -> QueryResponse:
    if agent.embedding_provider_mismatch:
        raise EmbeddingModelMismatchError()

    breakers = circuit_breakers or QueryPipelineCircuitBreakers()
    tracker = LatencyTracker()
    summary_tracker = LatencyTracker()
    scrubbed_query = scrub_pii(query)
    log_stage_latency(logger, "pii_scrub", tracker.elapsed_ms())

    try:
        tracker = LatencyTracker()
        route = await route_query(
            query=scrubbed_query,
            agent=agent,
            request_id=request_id,
            tenant_id=agent.tenant_id,
            circuit_breaker=breakers._cb_llm,
        )
        router_ms = tracker.elapsed_ms()

        if route == "direct":
            tracker = LatencyTracker()
            answer = await _execute_direct_generation(
                scrubbed_query=scrubbed_query,
                agent=agent,
                breakers=breakers,
            )
            generation_ms = tracker.elapsed_ms()
            log_stage_latency(logger, "generation", generation_ms)
            latency_ms = summary_tracker.elapsed_ms()
            logger.info(
                "query_pipeline",
                extra={
                    "operation": "query_pipeline",
                    "latency_ms": latency_ms,
                    "extra_data": {
                        "router_ms": router_ms,
                        "retrieval_ms": 0,
                        "reranker_ms": 0,
                        "generation_ms": generation_ms,
                        "tenant_id": agent.tenant_id,
                        "agent_id": agent.agent_id,
                    },
                },
            )
            return QueryResponse(
                answer=answer,
                confidence=0.0,
                citations=[],
                latency_ms=latency_ms,
                hallucination_risk=None,
            )

        rewriter_ms = 0
        retrieval_query = scrubbed_query
        if agent.query_rewrite:
            tracker = LatencyTracker()
            retrieval_query = await rewrite_query(
                scrubbed_query,
                agent,
                circuit_breaker=breakers._cb_llm,
            )
            rewriter_ms = tracker.elapsed_ms()

        tracker = LatencyTracker()
        retrieved_results = await _execute_retrieval(
            scrubbed_query=retrieval_query,
            top_k=top_k,
            agent=agent,
            filters=filters,
            breakers=breakers,
        )
        retrieval_ms = tracker.elapsed_ms()
        log_stage_latency(logger, "retrieval", retrieval_ms)

        tracker = LatencyTracker()
        results = await _execute_rerank(
            scrubbed_query=scrubbed_query,
            results=retrieved_results,
            top_k=top_k,
            agent=agent,
            breakers=breakers,
        )
        reranker_ms = tracker.elapsed_ms()
        log_stage_latency(logger, "reranking", reranker_ms)
        results = _apply_mmr_if_enabled(results=results, top_k=top_k, agent=agent)

        answer = ""
        generation_ms = 0
        hallucination_risk = None
        if results:
            tracker = LatencyTracker()
            answer = await _execute_generation(
                scrubbed_query=scrubbed_query,
                results=results,
                agent=agent,
                output_format=output_format,
                conversation_history=conversation_history,
                breakers=breakers,
            )
            generation_ms = tracker.elapsed_ms()
        log_stage_latency(logger, "generation", generation_ms)

        if agent.hallucination_check_enabled and results:
            tracker = LatencyTracker()
            hallucination_risk = await check_hallucination(answer=answer, results=results, agent=agent)
            log_stage_latency(logger, "hallucination_check", tracker.elapsed_ms())

        confidence = _compute_confidence(results)
        citations = [
            Citation(document_name=result.metadata.document_id, chunk_text=result.text, page_reference=None)
            for result in results
        ]
        latency_ms = summary_tracker.elapsed_ms()
        logger.info(
            "query_pipeline",
            extra={
                "operation": "query_pipeline",
                "latency_ms": latency_ms,
                "extra_data": {
                    "retrieval_ms": retrieval_ms,
                    "reranker_ms": reranker_ms,
                    "generation_ms": generation_ms,
                    "router_ms": router_ms,
                    "rewriter_ms": rewriter_ms,
                    "tenant_id": agent.tenant_id,
                    "agent_id": agent.agent_id,
                },
            },
        )
        return QueryResponse(
            answer=answer,
            confidence=confidence,
            citations=citations,
            latency_ms=latency_ms,
            hallucination_risk=hallucination_risk,
        )
    except CircuitOpenError as exc:
        raise ServiceUnavailableError("Provider circuit is open") from exc


def _sse_data(event: StreamEvent | str) -> str:
    if isinstance(event, str):
        return f"data: {event}\n\n"
    payload = event.model_dump(mode="json", exclude_none=True)
    return f"data: {json.dumps(payload)}\n\n"


async def _stream_generation(
    *,
    llm_provider_name: str,
    prompt: str,
    chunks: list[Chunk],
    circuit_breaker: CircuitBreaker,
) -> AsyncGenerator[str, None]:
    llm_cls = LLM_REGISTRY.get(llm_provider_name)
    if not llm_cls:
        raise ProviderUnavailableError(f"LLM provider '{llm_provider_name}' not registered")
    llm = llm_cls()

    # Prefer provider-native token streaming; fallback to single-shot generation.
    stream_generate = getattr(llm, "stream_generate", None)
    if callable(stream_generate):
        try:
            stream = stream_generate(prompt, chunks)
            async for token in stream:
                yield token
            return
        except NotImplementedError:
            pass

    answer = await circuit_breaker.call(llm.generate, prompt, chunks)
    if answer:
        yield answer


async def stream_query_pipeline(
    query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None = None,
    request_id: str | None = None,
    output_format: Literal["text", "json"] | None = None,
    conversation_history: list[ConversationMessage] | None = None,
    circuit_breakers: QueryPipelineCircuitBreakers | None = None,
) -> AsyncGenerator[str, None]:
    if agent.embedding_provider_mismatch:
        yield _sse_data(StreamEvent(type="error", message="Embedding model mismatch"))
        yield _sse_data("[DONE]")
        return

    breakers = circuit_breakers or QueryPipelineCircuitBreakers()
    tracker = LatencyTracker()
    summary_tracker = LatencyTracker()
    scrubbed_query = scrub_pii(query)
    log_stage_latency(logger, "pii_scrub", tracker.elapsed_ms())

    try:
        tracker = LatencyTracker()
        route = await route_query(
            query=scrubbed_query,
            agent=agent,
            request_id=request_id,
            tenant_id=agent.tenant_id,
            circuit_breaker=breakers._cb_llm,
        )
        router_ms = tracker.elapsed_ms()
        rewriter_ms = 0
        retrieval_ms = 0
        reranker_ms = 0
        generation_ms = 0
        confidence = 0.0
        citations: list[Citation] = []

        if route == "direct":
            tracker = LatencyTracker()
            async for token in _stream_generation(
                llm_provider_name=agent.llm_provider,
                prompt=scrubbed_query,
                chunks=[],
                circuit_breaker=breakers._cb_llm,
            ):
                if token:
                    yield _sse_data(StreamEvent(type="token", token=token))
            generation_ms = tracker.elapsed_ms()
            log_stage_latency(logger, "generation", generation_ms)
        else:
            retrieval_query = scrubbed_query
            if agent.query_rewrite:
                tracker = LatencyTracker()
                retrieval_query = await rewrite_query(
                    scrubbed_query,
                    agent,
                    circuit_breaker=breakers._cb_llm,
                )
                rewriter_ms = tracker.elapsed_ms()

            tracker = LatencyTracker()
            retrieved_results = await _execute_retrieval(
                scrubbed_query=retrieval_query,
                top_k=top_k,
                agent=agent,
                filters=filters,
                breakers=breakers,
            )
            retrieval_ms = tracker.elapsed_ms()
            log_stage_latency(logger, "retrieval", retrieval_ms)

            tracker = LatencyTracker()
            results = await _execute_rerank(
                scrubbed_query=scrubbed_query,
                results=retrieved_results,
                top_k=top_k,
                agent=agent,
                breakers=breakers,
            )
            reranker_ms = tracker.elapsed_ms()
            log_stage_latency(logger, "reranking", reranker_ms)
            results = _apply_mmr_if_enabled(results=results, top_k=top_k, agent=agent)

            confidence = _compute_confidence(results)
            citations = [
                Citation(document_name=result.metadata.document_id, chunk_text=result.text, page_reference=None)
                for result in results
            ]
            if results:
                context_chunks = [
                    Chunk(text=result.text, metadata=result.metadata, vector=None) for result in results
                ]
                prompt = _build_prompt(
                    scrubbed_query,
                    context_chunks,
                    output_format,
                    conversation_history=conversation_history,
                    context_window_tokens=getattr(agent, "context_window_tokens", 8192),
                )
                tracker = LatencyTracker()
                async for token in _stream_generation(
                    llm_provider_name=agent.llm_provider,
                    prompt=prompt,
                    chunks=context_chunks,
                    circuit_breaker=breakers._cb_llm,
                ):
                    if token:
                        yield _sse_data(StreamEvent(type="token", token=token))
                generation_ms = tracker.elapsed_ms()
            log_stage_latency(logger, "generation", generation_ms)

        latency_ms = summary_tracker.elapsed_ms()
        yield _sse_data(
            StreamEvent(
                type="done",
                confidence=confidence,
                citations=citations,
                latency_ms=latency_ms,
            )
        )
        yield _sse_data("[DONE]")
        logger.info(
            "query_pipeline_stream",
            extra={
                "operation": "query_pipeline_stream",
                "latency_ms": latency_ms,
                "extra_data": {
                    "retrieval_ms": retrieval_ms,
                    "reranker_ms": reranker_ms,
                    "generation_ms": generation_ms,
                    "router_ms": router_ms,
                    "rewriter_ms": rewriter_ms,
                    "tenant_id": agent.tenant_id,
                    "agent_id": agent.agent_id,
                },
            },
        )
    except CircuitOpenError as exc:
        yield _sse_data(StreamEvent(type="error", message=f"Provider circuit is open: {exc}"))
        yield _sse_data("[DONE]")
    except Exception as exc:
        yield _sse_data(StreamEvent(type="error", message=str(exc)))
        yield _sse_data("[DONE]")


async def _embed_text(
    *,
    embedder: object,
    text: str,
    breakers: QueryPipelineCircuitBreakers,
    provider_name: str,
) -> list[float]:
    vectors = await breakers._cb_embed.call(embedder.embed, [text])  # type: ignore[attr-defined]
    if not vectors:
        raise ProviderUnavailableError(
            f"Embedding provider '{provider_name}' returned no vectors for query"
        )
    return vectors[0]


def _rrf_merge(result_lists: list[list[VectorResult]], top_k: int, k: int = 60) -> list[VectorResult]:
    scores: dict[str, float] = {}
    best: dict[str, VectorResult] = {}
    for results in result_lists:
        for rank, result in enumerate(results):
            chunk_key = result.id
            scores[chunk_key] = scores.get(chunk_key, 0.0) + 1.0 / (rank + k)
            current = best.get(chunk_key)
            if current is None or result.score > current.score:
                best[chunk_key] = result
    ranked = sorted(best.values(), key=lambda item: scores.get(item.id, 0.0), reverse=True)
    return ranked[:top_k]


async def _standard_dense_retrieve(
    *,
    scrubbed_query: str,
    agent: AgentDocument,
    vector_store: object,
    embedder: object,
    namespace: str,
    top_k: int,
    filters: dict[str, str] | None,
    breakers: QueryPipelineCircuitBreakers,
) -> list[VectorResult]:
    query_vector = await _embed_text(
        embedder=embedder,
        text=scrubbed_query,
        breakers=breakers,
        provider_name=agent.embedding_provider,
    )
    query_kwargs: dict[str, object] = {}
    if agent.mmr_enabled:
        query_kwargs["include_embeddings"] = True
    return await breakers._cb_vector.call(
        vector_store.query,  # type: ignore[attr-defined]
        namespace,
        query_vector,
        top_k,
        filters,
        **query_kwargs,
    )


async def _hyde_retrieve(
    *,
    scrubbed_query: str,
    agent: AgentDocument,
    vector_store: object,
    embedder: object,
    namespace: str,
    top_k: int,
    filters: dict[str, str] | None,
    breakers: QueryPipelineCircuitBreakers,
) -> list[VectorResult]:
    try:
        llm_cls = LLM_REGISTRY.get(agent.llm_provider)
        if not llm_cls:
            raise ProviderUnavailableError(f"LLM provider '{agent.llm_provider}' not registered")
        llm = llm_cls()
        accumulator = get_cost_accumulator()
        before_prompt = accumulator.prompt_tokens if accumulator else 0
        before_completion = accumulator.completion_tokens if accumulator else 0

        prompt = f"{_HYDE_PROMPT}\n\nQuestion: {scrubbed_query}"
        hypothetical = await breakers._cb_llm.call(llm.generate, prompt, context=[])
        hypothetical_vector = await _embed_text(
            embedder=embedder,
            text=hypothetical,
            breakers=breakers,
            provider_name=agent.embedding_provider,
        )
        if accumulator:
            record_hyde_usage(
                accumulator.prompt_tokens - before_prompt,
                accumulator.completion_tokens - before_completion,
            )
        query_kwargs: dict[str, object] = {}
        if agent.mmr_enabled:
            query_kwargs["include_embeddings"] = True
        return await breakers._cb_vector.call(
            vector_store.query,  # type: ignore[attr-defined]
            namespace,
            hypothetical_vector,
            top_k,
            filters,
            **query_kwargs,
        )
    except Exception as exc:
        logger.warning(
            "hyde_retrieval_failed_fallback",
            extra={
                "operation": "retrieval",
                "extra_data": {
                    "tenant_id": agent.tenant_id,
                    "agent_id": agent.agent_id,
                    "error": str(exc),
                },
            },
        )
        return await _standard_dense_retrieve(
            scrubbed_query=scrubbed_query,
            agent=agent,
            vector_store=vector_store,
            embedder=embedder,
            namespace=namespace,
            top_k=top_k,
            filters=filters,
            breakers=breakers,
        )


def _parse_multi_query_variants(raw: str, query: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [query]
    if not isinstance(parsed, list):
        return [query]
    variants = [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
    return variants or [query]


async def _multi_query_retrieve(
    *,
    scrubbed_query: str,
    agent: AgentDocument,
    vector_store: object,
    embedder: object,
    namespace: str,
    top_k: int,
    filters: dict[str, str] | None,
    breakers: QueryPipelineCircuitBreakers,
) -> list[VectorResult]:
    try:
        llm_cls = LLM_REGISTRY.get(agent.llm_provider)
        if not llm_cls:
            raise ProviderUnavailableError(f"LLM provider '{agent.llm_provider}' not registered")
        llm = llm_cls()
        if agent.multi_query_count * top_k > 500:
            logger.warning(
                "multi_query_high_fanout",
                extra={
                    "operation": "retrieval",
                    "extra_data": {
                        "tenant_id": agent.tenant_id,
                        "agent_id": agent.agent_id,
                        "multi_query_count": agent.multi_query_count,
                        "top_k": top_k,
                    },
                },
            )

        prompt = _MULTI_QUERY_PROMPT_TEMPLATE.format(
            count=agent.multi_query_count,
            query=scrubbed_query,
        )
        raw = await breakers._cb_llm.call(llm.generate, prompt, context=[])
        variants = _parse_multi_query_variants(raw, scrubbed_query)[: agent.multi_query_count]

        vectors = await asyncio.gather(
            *[
                _embed_text(
                    embedder=embedder,
                    text=variant,
                    breakers=breakers,
                    provider_name=agent.embedding_provider,
                )
                for variant in variants
            ]
        )
        result_lists = await asyncio.gather(
            *[
                breakers._cb_vector.call(
                    vector_store.query,  # type: ignore[attr-defined]
                    namespace,
                    vector,
                    top_k,
                    filters,
                    **({"include_embeddings": True} if agent.mmr_enabled else {}),
                )
                for vector in vectors
            ]
        )
        return _rrf_merge(result_lists=result_lists, top_k=top_k)
    except Exception as exc:
        logger.warning(
            "multi_query_retrieval_failed_fallback",
            extra={
                "operation": "retrieval",
                "extra_data": {
                    "tenant_id": agent.tenant_id,
                    "agent_id": agent.agent_id,
                    "error": str(exc),
                },
            },
        )
        return await _standard_dense_retrieve(
            scrubbed_query=scrubbed_query,
            agent=agent,
            vector_store=vector_store,
            embedder=embedder,
            namespace=namespace,
            top_k=top_k,
            filters=filters,
            breakers=breakers,
        )


async def _dense_retrieve_with_strategies(
    *,
    scrubbed_query: str,
    agent: AgentDocument,
    vector_store: object,
    embedder: object,
    namespace: str,
    top_k: int,
    filters: dict[str, str] | None,
    breakers: QueryPipelineCircuitBreakers,
) -> list[VectorResult]:
    if agent.hyde_enabled and agent.multi_query_enabled:
        logger.warning(
            "hyde_and_multi_query_both_enabled_hyde_precedence",
            extra={
                "operation": "retrieval",
                "extra_data": {
                    "tenant_id": agent.tenant_id,
                    "agent_id": agent.agent_id,
                },
            },
        )

    if agent.hyde_enabled:
        return await _hyde_retrieve(
            scrubbed_query=scrubbed_query,
            agent=agent,
            vector_store=vector_store,
            embedder=embedder,
            namespace=namespace,
            top_k=top_k,
            filters=filters,
            breakers=breakers,
        )
    if agent.multi_query_enabled:
        return await _multi_query_retrieve(
            scrubbed_query=scrubbed_query,
            agent=agent,
            vector_store=vector_store,
            embedder=embedder,
            namespace=namespace,
            top_k=top_k,
            filters=filters,
            breakers=breakers,
        )
    return await _standard_dense_retrieve(
        scrubbed_query=scrubbed_query,
        agent=agent,
        vector_store=vector_store,
        embedder=embedder,
        namespace=namespace,
        top_k=top_k,
        filters=filters,
        breakers=breakers,
    )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    try:
        import numpy as np  # type: ignore[import-not-found]

        a_arr = np.array(a, dtype=float)
        b_arr = np.array(b, dtype=float)
        denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
        if denom <= 1e-12:
            return 0.0
        return float(np.dot(a_arr, b_arr) / denom)
    except Exception:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        denom = norm_a * norm_b
        if denom <= 1e-12:
            return 0.0
        return dot / denom


def _mmr_filter(results: list[VectorResult], top_k: int, lambda_: float) -> list[VectorResult]:
    if not results:
        return []
    selected: list[VectorResult] = []
    remaining = list(results)
    while remaining and len(selected) < top_k:
        if not selected:
            best = max(remaining, key=lambda item: item.score)
        else:
            best = max(
                remaining,
                key=lambda item: (
                    lambda_ * item.score
                    - (1.0 - lambda_)
                    * max(
                        _cosine_similarity(item.embedding or [], chosen.embedding or [])
                        for chosen in selected
                    )
                ),
            )
        selected.append(best)
        remaining.remove(best)
    return selected


def _apply_mmr_if_enabled(
    *,
    results: list[VectorResult],
    top_k: int,
    agent: AgentDocument,
) -> list[VectorResult]:
    if not agent.mmr_enabled:
        return results[:top_k]
    try:
        with_embeddings = [result for result in results if result.embedding is not None]
        missing = len(results) - len(with_embeddings)
        if missing > 0:
            logger.warning(
                "mmr_missing_embeddings",
                extra={
                    "operation": "retrieval",
                    "extra_data": {
                        "tenant_id": agent.tenant_id,
                        "agent_id": agent.agent_id,
                        "missing_embeddings": missing,
                    },
                },
            )
        if not with_embeddings:
            raise ValueError("No embeddings available for MMR")
        return _mmr_filter(with_embeddings, top_k, agent.mmr_lambda)
    except Exception as exc:
        logger.warning(
            "mmr_failed_fallback",
            extra={
                "operation": "retrieval",
                "extra_data": {
                    "tenant_id": agent.tenant_id,
                    "agent_id": agent.agent_id,
                    "error": str(exc),
                },
            },
        )
        return results[:top_k]


async def _execute_retrieval(
    scrubbed_query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None,
    breakers: QueryPipelineCircuitBreakers | None = None,
) -> list[VectorResult]:
    active_breakers = breakers or QueryPipelineCircuitBreakers()
    retrieval_top_k = _get_retrieval_pool_size(agent=agent, top_k=top_k)
    vector_store_cls = VECTOR_STORE_REGISTRY.get(agent.vector_store)
    if not vector_store_cls:
        raise ProviderUnavailableError(f"Vector store '{agent.vector_store}' not registered")
    vector_store = vector_store_cls()
    namespace = f"{agent.tenant_id}_{agent.agent_id}"

    retrieval_mode = agent.retrieval_mode
    if retrieval_mode == "sparse":
        try:
            return await active_breakers._cb_vector.call(
                retrieve_sparse,
                query=scrubbed_query,
                agent=agent,
                vector_store=vector_store,
                top_k=retrieval_top_k,
            )
        except ProviderUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover
            raise ProviderUnavailableError(f"Sparse retrieval failed: {exc}") from exc

    embedder_cls = EMBEDDING_REGISTRY.get(agent.embedding_provider)
    if not embedder_cls:
        raise ProviderUnavailableError(f"Embedding provider '{agent.embedding_provider}' not registered")
    embedder = embedder_cls()

    logger.info(
        "embedding_complete",
        extra={
            "operation": "embedding",
            "extra_data": {
                "tenant_id": agent.tenant_id,
                "agent_id": agent.agent_id,
                "provider": agent.embedding_provider,
            },
        },
    )

    if retrieval_mode == "hybrid":
        try:
            dense_results, sparse_results = await asyncio.gather(
                _dense_retrieve_with_strategies(
                    scrubbed_query=scrubbed_query,
                    agent=agent,
                    vector_store=vector_store,
                    embedder=embedder,
                    namespace=namespace,
                    top_k=retrieval_top_k,
                    filters=filters,
                    breakers=active_breakers,
                ),
                active_breakers._cb_vector.call(
                    retrieve_sparse,
                    query=scrubbed_query,
                    agent=agent,
                    vector_store=vector_store,
                    top_k=retrieval_top_k,
                ),
            )
            results = reciprocal_rank_fusion(dense_results=dense_results, sparse_results=sparse_results)[
                :retrieval_top_k
            ]
        except (ProviderUnavailableError, CircuitOpenError):
            raise
        except Exception as exc:  # pragma: no cover
            raise ProviderUnavailableError(f"Hybrid retrieval failed: {exc}") from exc
    else:
        try:
            results = await _dense_retrieve_with_strategies(
                scrubbed_query=scrubbed_query,
                agent=agent,
                vector_store=vector_store,
                embedder=embedder,
                namespace=namespace,
                top_k=retrieval_top_k,
                filters=filters,
                breakers=active_breakers,
            )
        except (ProviderUnavailableError, CircuitOpenError):
            raise
        except Exception as exc:  # pragma: no cover
            raise ProviderUnavailableError(f"Dense retrieval failed: {exc}") from exc

    logger.info(
        "retrieval_complete",
        extra={
            "operation": "retrieval",
            "extra_data": {
                "tenant_id": agent.tenant_id,
                "agent_id": agent.agent_id,
                "chunk_count": len(results),
                "provider": agent.vector_store,
            },
        },
    )

    return results


def _get_retrieval_pool_size(agent: AgentDocument, top_k: int) -> int:
    if agent.reranker == "none":
        return top_k
    return max(top_k, agent.rerank_pool_size)


async def _execute_rerank(
    scrubbed_query: str,
    results: list[VectorResult],
    top_k: int,
    agent: AgentDocument,
    breakers: QueryPipelineCircuitBreakers,
) -> list[VectorResult]:
    reranker_cls = RERANKER_REGISTRY.get(agent.reranker)
    if not reranker_cls:
        raise ProviderUnavailableError(f"Reranker '{agent.reranker}' not registered")
    reranker = reranker_cls()
    chunks = [Chunk(text=result.text, metadata=result.metadata, vector=None) for result in results]

    async def _call_rerank() -> list[Chunk]:
        return reranker.rerank(scrubbed_query, chunks, top_k)

    reranked_chunks = await breakers._cb_rerank.call(_call_rerank)
    reranked_by_text = {chunk.text: chunk for chunk in reranked_chunks[:top_k]}
    reranked_results = [result for result in results if result.text in reranked_by_text]
    return reranked_results[:top_k]


async def _execute_generation(
    scrubbed_query: str,
    results: list[VectorResult],
    agent: AgentDocument,
    output_format: Literal["text", "json"] | None,
    conversation_history: list[ConversationMessage] | None,
    breakers: QueryPipelineCircuitBreakers,
) -> str:
    return await generate_answer(
        query=scrubbed_query,
        results=results,
        llm_provider_name=agent.llm_provider,
        output_format=output_format,
        conversation_history=conversation_history,
        context_window_tokens=getattr(agent, "context_window_tokens", 8192),
        circuit_breaker=breakers._cb_llm,
    )


async def _execute_direct_generation(
    scrubbed_query: str,
    agent: AgentDocument,
    breakers: QueryPipelineCircuitBreakers,
) -> str:
    llm_cls = LLM_REGISTRY.get(agent.llm_provider)
    if not llm_cls:
        raise ProviderUnavailableError(f"LLM provider '{agent.llm_provider}' not registered")
    llm = llm_cls()
    return await breakers._cb_llm.call(llm.generate, scrubbed_query, context=[])


def _compute_confidence(results: list[VectorResult]) -> float:
    if not results:
        return 0.0
    return max(0.0, min(1.0, mean(result.score for result in results)))
