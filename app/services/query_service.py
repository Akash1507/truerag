from app.models.query import QueryRequest, QueryResponse
from app.pipelines.query.pipeline import run_query_pipeline
from app.services import agent_service


async def handle_query(
    agent_id: str,
    tenant_id: str,
    request: QueryRequest,
) -> QueryResponse:
    agent = await agent_service.get_agent(agent_id, tenant_id)
    effective_top_k = request.top_k if request.top_k is not None else agent.top_k
    return await run_query_pipeline(query=request.query, top_k=effective_top_k, agent=agent)
