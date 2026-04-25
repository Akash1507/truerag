from fastapi import APIRouter, Depends, Query, Request, status

from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.core.errors import ForbiddenError, InvalidCursorError
from app.models.agent import AgentCreateRequest, AgentCreateResponse, AgentListResponse
from app.models.tenant import TenantDocument
from app.services import agent_service
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentCreateResponse)
async def create_agent_route(
    body: AgentCreateRequest,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentCreateResponse:
    if body.tenant_id is not None and body.tenant_id != caller.tenant_id:
        raise ForbiddenError("Cannot create agent for a different tenant")
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    agent = await agent_service.create_agent(body, caller.tenant_id, db)
    return AgentCreateResponse(**agent.model_dump())


@router.get("", response_model=AgentListResponse)
async def list_agents_route(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentListResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    try:
        items, next_cursor = await agent_service.list_agents(caller.tenant_id, db, cursor, limit)
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc
    return AgentListResponse(
        items=[AgentCreateResponse(**item.model_dump()) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/{agent_id}", response_model=AgentCreateResponse)
async def get_agent_route(
    agent_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentCreateResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    agent = await agent_service.get_agent(agent_id, caller.tenant_id, db)
    return AgentCreateResponse(**agent.model_dump())
