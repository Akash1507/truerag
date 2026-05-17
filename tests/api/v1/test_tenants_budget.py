import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import tenants
from app.core.auth import AuthMiddleware
from app.core.errors import TrueRAGError
from app.core.exception_handlers import generic_exception_handler, truerag_exception_handler
from app.core.middleware import RequestIDMiddleware
from app.models.tenant import TenantDocument


def _tenant(role: str, budget: int | None = None, api_key: str = "key") -> TenantDocument:
    return TenantDocument.model_construct(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
        rate_limit_rpm=60,
        role=role,  # type: ignore[arg-type]
        monthly_token_budget=budget,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def test_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(TrueRAGError, truerag_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(tenants.router, prefix="/v1/tenants")
    return app


@pytest.fixture
async def api_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_patch_budget_as_admin_returns_200(api_client: AsyncClient) -> None:
    updated = _tenant("agent_owner", budget=500000)

    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant("admin"))), patch(
        "app.api.v1.tenants.tenant_service.update_budget",
        AsyncMock(return_value=updated),
    ) as update_budget_mock:
        response = await api_client.patch(
            "/v1/tenants/tenant-1/budget",
            json={"monthly_token_budget": 500000},
            headers={"X-API-Key": "key"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-1"
    assert body["monthly_token_budget"] == 500000
    update_budget_mock.assert_awaited_once_with("tenant-1", 500000)


@pytest.mark.asyncio
async def test_patch_budget_as_non_admin_returns_403(api_client: AsyncClient) -> None:
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant("agent_owner"))), patch(
        "app.api.v1.tenants.tenant_service.update_budget",
        AsyncMock(),
    ) as update_budget_mock:
        response = await api_client.patch(
            "/v1/tenants/tenant-1/budget",
            json={"monthly_token_budget": 500000},
            headers={"X-API-Key": "key"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    update_budget_mock.assert_not_awaited()
