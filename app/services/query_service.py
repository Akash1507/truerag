import hashlib

from fastapi import BackgroundTasks

from app.models.query import QueryRequest, QueryResponse
from app.pipelines.query.pipeline import run_query_pipeline
from app.services import agent_service, audit_service
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
    try:
        response = await run_query_pipeline(
            query=request.query,
            top_k=effective_top_k,
            agent=agent,
            filters=request.filters,
            output_format=request.output_format,
        )
        return response
    finally:
        background_tasks.add_task(
            audit_service.write_audit_log,
            tenant_id=tenant_id,
            agent_id=agent_id,
            api_key_hash=api_key_hash,
            query_hash=query_hash,
            response_confidence=response.confidence if response is not None else 0.0,
            cache_hit=False,
        )
