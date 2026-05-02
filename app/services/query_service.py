import hashlib
import time

from fastapi import BackgroundTasks

from app.core.errors import ProviderUnavailableError
from app.models.query import QueryRequest, QueryResponse
from app.pipelines.query.pipeline import run_query_pipeline
from app.providers.registry import EMBEDDING_REGISTRY
from app.services import agent_service, audit_service
from app.utils import semantic_cache
from app.utils.pii import scrub_pii


async def handle_query(
    agent_id: str,
    tenant_id: str,
    api_key_hash: str,
    request: QueryRequest,
    background_tasks: BackgroundTasks,
) -> QueryResponse:
    agent = await agent_service.get_agent(agent_id, tenant_id)
    effective_top_k = request.top_k if request.top_k is not None else agent.top_k
    scrubbed = scrub_pii(request.query)
    query_hash = hashlib.sha256(scrubbed.encode()).hexdigest()

    response: QueryResponse | None = None
    cache_hit = False
    t0 = time.perf_counter()
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
                cached = await semantic_cache.lookup(
                    agent_id,
                    query_vector,
                    agent.semantic_cache_threshold,
                )
                if cached is not None:
                    cache_hit = True
                    response = QueryResponse(
                        answer=cached,
                        confidence=1.0,
                        citations=[],
                        latency_ms=round((time.perf_counter() - t0) * 1000),
                    )
                    return response

        response = await run_query_pipeline(
            query=request.query,
            top_k=effective_top_k,
            agent=agent,
            filters=request.filters,
            output_format=request.output_format,
        )

        if (
            agent.semantic_cache_enabled
            and agent.semantic_cache_threshold is not None
            and query_vector is not None
        ):
            await semantic_cache.store(agent_id, query_vector, query_hash, response.answer)

        return response
    finally:
        background_tasks.add_task(
            audit_service.write_audit_log,
            tenant_id=tenant_id,
            agent_id=agent_id,
            api_key_hash=api_key_hash,
            query_hash=query_hash,
            response_confidence=response.confidence if response is not None else 0.0,
            cache_hit=cache_hit,
        )
