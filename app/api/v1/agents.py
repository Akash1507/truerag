from fastapi import APIRouter, Depends, Query, Request, status

from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.models.agent import (
    AgentConfigUpdateRequest,
    AgentCreateRequest,
    AgentCreateResponse,
    AgentListResponse,
    AgentUpdateResponse,
)
from app.models.tenant import TenantDocument
from app.services.agent_service import agent_service
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentCreateResponse)
async def create_agent_route(
    body: AgentCreateRequest,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentCreateResponse:
    return await agent_service.create(body, caller.tenant_id)


@router.get("", response_model=AgentListResponse)
async def list_agents_route(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentListResponse:
    return await agent_service.list(caller.tenant_id, cursor, limit)


@router.get("/{agent_id}", response_model=AgentCreateResponse)
async def get_agent_route(
    agent_id: str,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentCreateResponse:
    return await agent_service.get(agent_id, caller.tenant_id)


@router.patch("/{agent_id}/config", response_model=AgentUpdateResponse)
async def update_agent_config_route(
    agent_id: str,
    body: AgentConfigUpdateRequest,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> AgentUpdateResponse:
    return await agent_service.update_config(agent_id, caller.tenant_id, body)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_route(
    agent_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> None:
    await agent_service.delete(
        agent_id, caller.tenant_id, request.app.state.aws_session, get_settings()
    )
