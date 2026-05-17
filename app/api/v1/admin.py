from fastapi import APIRouter, Depends

from app.core.auth import require_role
from app.models.tenant import AdminTenantListResponse, TenantDocument
from app.services.tenant_service import tenant_service

router = APIRouter()


@router.get("/tenants", response_model=AdminTenantListResponse)
async def admin_list_tenants(
    _: TenantDocument = Depends(require_role("admin")),  
) -> AdminTenantListResponse:
    return await tenant_service.admin_list_tenants()
