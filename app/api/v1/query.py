from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.core.auth import get_current_tenant
from app.models.query import QueryRequest, QueryResponse
from app.models.tenant import TenantDocument
from app.services import query_service
from app.utils.observability import reset_request_context, set_request_context

router = APIRouter()


@router.post("/{agent_id}/query", response_model=QueryResponse, status_code=200)
async def query_agent_route(
    agent_id: str,
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> QueryResponse:
    http_request.state.background_tasks = background_tasks
    request_id = getattr(http_request.state, "request_id", "")
    tokens = set_request_context(
        request_id=request_id,
        tenant_id=caller.tenant_id,
        agent_id=agent_id,
    )
    try:
        return await query_service.handle_query(
            agent_id=agent_id,
            tenant_id=caller.tenant_id,
            api_key_hash=caller.api_key_hash,
            request=request,
            background_tasks=background_tasks,
        )
    finally:
        reset_request_context(tokens)
