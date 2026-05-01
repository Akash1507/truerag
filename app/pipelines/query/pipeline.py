import time

from app.core.errors import ProviderUnavailableError
from app.models.agent import AgentDocument
from app.models.query import Citation, QueryResponse
from app.providers.registry import EMBEDDING_REGISTRY, VECTOR_STORE_REGISTRY
from app.utils.observability import get_logger
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


async def run_query_pipeline(
    query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None = None,
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
    response = await _execute_retrieval(
        scrubbed_query=scrubbed_query,
        top_k=top_k,
        agent=agent,
        filters=filters,
    )
    latency_ms = round((time.perf_counter() - t0) * 1000)
    return response.model_copy(update={"latency_ms": latency_ms})


async def _execute_retrieval(
    scrubbed_query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None,
) -> QueryResponse:
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

    citations = [
        Citation(document_name=result.metadata.document_id, chunk_text=result.text, page_reference=None)
        for result in results
    ]
    return QueryResponse(answer="", confidence=0.0, citations=citations, latency_ms=0)
