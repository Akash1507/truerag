from fastapi import APIRouter, Depends, Query, status

from app.core.auth import get_current_tenant, require_role
from app.models.tenant import (
    MeResponse,
    TenantBudgetResponse,
    TenantBudgetUpdateRequest,
    TenantCreateRequest,
    TenantCreateResponse,
    TenantDocument,
    TenantListResponse,
    TenantUpdateRequest,
    TenantUpdateResponse,
)
from app.services.tenant_service import tenant_service
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()


@router.get("/me", response_model=MeResponse)
async def get_me(tenant: TenantDocument = Depends(get_current_tenant)) -> MeResponse:  
    return await tenant_service.get_me(tenant)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantCreateResponse)
async def register_tenant(
    body: TenantCreateRequest,
    _: TenantDocument = Depends(require_role("admin")),  
) -> TenantCreateResponse:
    return await tenant_service.register(body.name, body.display_name)


@router.get("", response_model=TenantListResponse)
async def list_tenants_route(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    _: TenantDocument = Depends(require_role("admin")),  
) -> TenantListResponse:
    return await tenant_service.list(cursor, limit)


@router.patch("/{tenant_id}", response_model=TenantUpdateResponse)
async def update_tenant_route(
    tenant_id: str,
    body: TenantUpdateRequest,
    _: TenantDocument = Depends(require_role("admin")),  
) -> TenantUpdateResponse:
    return await tenant_service.update_tenant(tenant_id, body)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_route(
    tenant_id: str,
    _: TenantDocument = Depends(require_role("admin")),  
) -> None:
    await tenant_service.delete_tenant(tenant_id)


@router.patch(
    "/{tenant_id}/budget",
    response_model=TenantBudgetResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def update_tenant_budget_route(
    tenant_id: str,
    body: TenantBudgetUpdateRequest,
) -> TenantBudgetResponse:
    return await tenant_service.update_budget(tenant_id, body.monthly_token_budget)
