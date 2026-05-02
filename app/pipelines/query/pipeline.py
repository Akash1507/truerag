import asyncio
import time
from statistics import mean
from typing import Literal

from app.core.errors import ProviderUnavailableError
from app.models.agent import AgentDocument
from app.models.chunk import VectorResult
from app.models.query import Citation, QueryResponse
from app.pipelines.query.generator import generate_answer
from app.pipelines.query.rewriter import rewrite_query
from app.pipelines.query.router import route_query
from app.pipelines.query.rrf import reciprocal_rank_fusion
from app.pipelines.query.sparse_retriever import retrieve_sparse
from app.providers.registry import EMBEDDING_REGISTRY, LLM_REGISTRY, RERANKER_REGISTRY, VECTOR_STORE_REGISTRY
from app.utils.observability import get_logger
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


async def run_query_pipeline(
    query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None = None,
    output_format: Literal["text", "json"] | None = None,
    request_id: str | None = None,
) -> QueryResponse:
    t0 = time.perf_counter()
    scrubbed_query = scrub_pii(query)
    logger.info(
        "pii_scrub",
        extra={
            "operation": "pii_scrub",
            "extra_data": {"agent_id": agent.agent_id, "tenant_id": agent.tenant_id},
        },
    )
    t_router = time.perf_counter()
    route = await route_query(
        query=scrubbed_query,
        agent=agent,
        request_id=request_id,
        tenant_id=agent.tenant_id,
    )
    router_ms = round((time.perf_counter() - t_router) * 1000)
    if route == "direct":
        t_generation = time.perf_counter()
        answer = await _execute_direct_generation(scrubbed_query=scrubbed_query, agent=agent)
        generation_ms = round((time.perf_counter() - t_generation) * 1000)
        latency_ms = round((time.perf_counter() - t0) * 1000)
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
        return QueryResponse(answer=answer, confidence=0.0, citations=[], latency_ms=latency_ms)

    rewriter_ms = 0
    retrieval_query = scrubbed_query
    if agent.query_rewrite:
        t_rewriter = time.perf_counter()
        retrieval_query = await rewrite_query(scrubbed_query, agent)
        rewriter_ms = round((time.perf_counter() - t_rewriter) * 1000)

    t_retrieval = time.perf_counter()
    retrieved_results = await _execute_retrieval(
        scrubbed_query=retrieval_query,
        top_k=top_k,
        agent=agent,
        filters=filters,
    )
    retrieval_ms = round((time.perf_counter() - t_retrieval) * 1000)
    t_reranker = time.perf_counter()
    results = _execute_rerank(
        scrubbed_query=scrubbed_query,
        results=retrieved_results,
        top_k=top_k,
        agent=agent,
    )
    reranker_ms = round((time.perf_counter() - t_reranker) * 1000)
    answer = ""
    t_generation = time.perf_counter()
    if results:
        answer = await _execute_generation(
            scrubbed_query=scrubbed_query,
            results=results,
            agent=agent,
            output_format=output_format,
        )
    generation_ms = round((time.perf_counter() - t_generation) * 1000)
    confidence = _compute_confidence(results)
    citations = [
        Citation(document_name=result.metadata.document_id, chunk_text=result.text, page_reference=None)
        for result in results
    ]
    latency_ms = round((time.perf_counter() - t0) * 1000)
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
    return QueryResponse(answer=answer, confidence=confidence, citations=citations, latency_ms=latency_ms)


async def _execute_retrieval(
    scrubbed_query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None,
) -> list[VectorResult]:
    retrieval_top_k = _get_retrieval_pool_size(agent=agent, top_k=top_k)
    vector_store_cls = VECTOR_STORE_REGISTRY.get(agent.vector_store)
    if not vector_store_cls:
        raise ProviderUnavailableError(f"Vector store '{agent.vector_store}' not registered")
    vector_store = vector_store_cls()
    namespace = f"{agent.tenant_id}_{agent.agent_id}"

    retrieval_mode = agent.retrieval_mode
    if retrieval_mode == "sparse":
        try:
            return await retrieve_sparse(
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
    vectors = await embedder.embed([scrubbed_query])
    if not vectors:
        raise ProviderUnavailableError(
            f"Embedding provider '{agent.embedding_provider}' returned no vectors for query"
        )
    query_vector = vectors[0]

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
                vector_store.query(namespace, query_vector, retrieval_top_k, filters),
                retrieve_sparse(
                    query=scrubbed_query,
                    agent=agent,
                    vector_store=vector_store,
                    top_k=retrieval_top_k,
                ),
            )
            results = reciprocal_rank_fusion(dense_results=dense_results, sparse_results=sparse_results)[
                :retrieval_top_k
            ]
        except ProviderUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover
            raise ProviderUnavailableError(f"Hybrid retrieval failed: {exc}") from exc
    else:
        try:
            results = await vector_store.query(namespace, query_vector, retrieval_top_k, filters)
        except ProviderUnavailableError:
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


def _execute_rerank(
    scrubbed_query: str,
    results: list[VectorResult],
    top_k: int,
    agent: AgentDocument,
) -> list[VectorResult]:
    reranker_cls = RERANKER_REGISTRY.get(agent.reranker)
    if not reranker_cls:
        raise ProviderUnavailableError(f"Reranker '{agent.reranker}' not registered")
    reranker = reranker_cls()
    reranked = reranker.rerank(scrubbed_query, results, top_k)
    return reranked[:top_k]


async def _execute_generation(
    scrubbed_query: str,
    results: list[VectorResult],
    agent: AgentDocument,
    output_format: Literal["text", "json"] | None,
) -> str:
    return await generate_answer(
        query=scrubbed_query,
        results=results,
        llm_provider_name=agent.llm_provider,
        output_format=output_format,
    )


async def _execute_direct_generation(scrubbed_query: str, agent: AgentDocument) -> str:
    llm_cls = LLM_REGISTRY.get(agent.llm_provider)
    if not llm_cls:
        raise ProviderUnavailableError(f"LLM provider '{agent.llm_provider}' not registered")
    llm = llm_cls()
    return await llm.generate(scrubbed_query, context=[])


def _compute_confidence(results: list[VectorResult]) -> float:
    if not results:
        return 0.0
    return max(0.0, min(1.0, mean(result.score for result in results)))
