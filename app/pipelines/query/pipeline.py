import time
from statistics import mean
from typing import Literal

from app.core.errors import ProviderUnavailableError
from app.models.agent import AgentDocument
from app.models.chunk import VectorResult
from app.models.query import Citation, QueryResponse
from app.pipelines.query.generator import generate_answer
from app.providers.registry import EMBEDDING_REGISTRY, VECTOR_STORE_REGISTRY
from app.utils.observability import get_logger
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


async def run_query_pipeline(
    query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None = None,
    output_format: Literal["text", "json"] | None = None,
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
    results = await _execute_retrieval(
        scrubbed_query=scrubbed_query,
        top_k=top_k,
        agent=agent,
        filters=filters,
    )
    answer = ""
    if results:
        answer = await _execute_generation(
            scrubbed_query=scrubbed_query,
            results=results,
            agent=agent,
            output_format=output_format,
        )
    confidence = _compute_confidence(results)
    citations = [
        Citation(document_name=result.metadata.document_id, chunk_text=result.text, page_reference=None)
        for result in results
    ]
    latency_ms = round((time.perf_counter() - t0) * 1000)
    return QueryResponse(answer=answer, confidence=confidence, citations=citations, latency_ms=latency_ms)


async def _execute_retrieval(
    scrubbed_query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None,
) -> list[VectorResult]:
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

    vector_store_cls = VECTOR_STORE_REGISTRY.get(agent.vector_store)
    if not vector_store_cls:
        raise ProviderUnavailableError(f"Vector store '{agent.vector_store}' not registered")
    vector_store = vector_store_cls()
    namespace = f"{agent.tenant_id}_{agent.agent_id}"
    results = await vector_store.query(namespace, query_vector, top_k, filters)

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


def _compute_confidence(results: list[VectorResult]) -> float:
    if not results:
        return 0.0
    return max(0.0, min(1.0, mean(result.score for result in results)))
