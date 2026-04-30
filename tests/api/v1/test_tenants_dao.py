from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.tenant import TenantDocument, TenantListItem


def _tenant() -> TenantDocument:
    return TenantDocument(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash="hash",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_register_tenant_uses_service_and_returns_201() -> None:
    app = create_app()
    with patch("app.api.v1.tenants.tenant_service.create_tenant", AsyncMock(return_value=(_tenant(), "raw-key"))):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/tenants", json={"name": "tenant-1"})

    assert response.status_code == 201
    assert response.json()["api_key"] == "raw-key"


@pytest.mark.asyncio
async def test_list_tenants_route_returns_service_page() -> None:
    app = create_app()
    item = TenantListItem(
        tenant_id="tenant-1",
        name="tenant-1",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.tenants.tenant_service.list_tenants",
        AsyncMock(return_value=([item], "cursor-1")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/tenants", headers={"X-API-Key": "key"})

    assert response.status_code == 200
    assert response.json()["next_cursor"] == "cursor-1"
