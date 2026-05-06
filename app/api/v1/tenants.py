from fastapi import APIRouter, Depends, Query, status

from app.core.auth import get_current_tenant
from app.core.errors import ForbiddenError
from app.models.tenant import (
    TenantCreateRequest,
    TenantCreateResponse,
    TenantDocument,
    TenantListResponse,
)
from app.services.tenant_service import tenant_service
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantCreateResponse)
async def register_tenant(body: TenantCreateRequest) -> TenantCreateResponse:
    return await tenant_service.register(body.name)


@router.get("", response_model=TenantListResponse)
async def list_tenants_route(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    _: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> TenantListResponse:
    return await tenant_service.list(cursor, limit)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_route(
    tenant_id: str,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> None:
    if caller.tenant_id != tenant_id:
        raise ForbiddenError("Tenants may only delete themselves")
    await tenant_service.delete_tenant(tenant_id)
