import hashlib
from datetime import UTC, datetime
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core import rate_limiter as rl_module
from app.models.tenant import TenantDocument


def _tenant(rpm: int | None = 2) -> TenantDocument:
    return TenantDocument(
        tenant_id="tenant-a",
        name="tenant-a",
        api_key_hash=hashlib.sha256(b"key-a").hexdigest(),
        rate_limit_rpm=rpm,
        created_at=datetime.now(UTC),
    )


def _build_app() -> FastAPI:
    from app.core.auth import AuthMiddleware
    from app.core.middleware import RequestIDMiddleware
    from app.core.rate_limiter import RateLimiterMiddleware

    app = FastAPI()

    @app.get("/protected")
    async def protected() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/v1/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app.add_middleware(RateLimiterMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestIDMiddleware)
    return app


@pytest.fixture(autouse=True)
def clear_counters() -> Generator[None, None, None]:
    rl_module._counters.clear()
    yield
    rl_module._counters.clear()


@pytest.mark.asyncio
async def test_over_limit_returns_429() -> None:
    app = _build_app()
    tenant = _tenant(2)
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=tenant)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/protected", headers={"X-API-Key": "key-a"})
            await client.get("/protected", headers={"X-API-Key": "key-a"})
            response = await client.get("/protected", headers={"X-API-Key": "key-a"})

    assert response.status_code == 429


@pytest.mark.asyncio
async def test_health_not_rate_limited() -> None:
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/health")
    assert response.status_code == 200
