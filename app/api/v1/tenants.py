from fastapi import APIRouter, Depends, Query, Request, status

from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.core.errors import ForbiddenError, InvalidCursorError
from app.models.tenant import (
    TenantCreateRequest,
    TenantCreateResponse,
    TenantDocument,
    TenantListResponse,
)
from app.services import tenant_service
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantCreateResponse)
async def register_tenant(body: TenantCreateRequest, request: Request) -> TenantCreateResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    tenant, raw_key = await tenant_service.create_tenant(body.name, db)
    return TenantCreateResponse(
        tenant_id=tenant.tenant_id,
        name=tenant.name,
        api_key=raw_key,
        rate_limit_rpm=(
            tenant.rate_limit_rpm
            if tenant.rate_limit_rpm is not None
            else settings.default_rate_limit_rpm
        ),
        created_at=tenant.created_at,
    )


@router.get("", response_model=TenantListResponse)
async def list_tenants_route(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    _: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> TenantListResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    try:
        items, next_cursor = await tenant_service.list_tenants(db, cursor, limit)
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc
    return TenantListResponse(items=items, next_cursor=next_cursor)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_route(
    tenant_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> None:
    if caller.tenant_id != tenant_id:
        raise ForbiddenError("Tenants may only delete themselves")
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    await tenant_service.delete_tenant(tenant_id, db)
