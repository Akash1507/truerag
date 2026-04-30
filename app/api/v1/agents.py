from fastapi import APIRouter, Depends, Query, Request, status

from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.core.errors import InvalidCursorError
from app.models.agent import (
    AgentConfigUpdateRequest,
    AgentCreateRequest,
    AgentCreateResponse,
    AgentListResponse,
    AgentUpdateResponse,
)
from app.models.tenant import TenantDocument
from app.services import agent_service
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentCreateResponse)
async def create_agent_route(
    body: AgentCreateRequest,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentCreateResponse:
    agent = await agent_service.create_agent(body, caller.tenant_id)
    return AgentCreateResponse(**agent.model_dump())


@router.get("", response_model=AgentListResponse)
async def list_agents_route(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentListResponse:
    try:
        items, next_cursor = await agent_service.list_agents(caller.tenant_id, cursor, limit)
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc
    return AgentListResponse(
        items=[AgentCreateResponse(**item.model_dump()) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/{agent_id}", response_model=AgentCreateResponse)
async def get_agent_route(
    agent_id: str,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentCreateResponse:
    agent = await agent_service.get_agent(agent_id, caller.tenant_id)
    return AgentCreateResponse(**agent.model_dump())


@router.patch("/{agent_id}/config", response_model=AgentUpdateResponse)
async def update_agent_config_route(
    agent_id: str,
    body: AgentConfigUpdateRequest,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentUpdateResponse:
    agent, warnings = await agent_service.update_agent_config(agent_id, caller.tenant_id, body)
    return AgentUpdateResponse(**agent.model_dump(), warnings=warnings)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_route(
    agent_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> None:
    await agent_service.delete_agent(
        agent_id, caller.tenant_id, request.app.state.aws_session, get_settings()
    )
