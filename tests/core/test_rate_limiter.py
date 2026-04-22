import hashlib
import time
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core import rate_limiter as rl_module
from app.models.tenant import TenantDocument

_RAW_KEY = "test-api-key"
_KEY_HASH = hashlib.sha256(_RAW_KEY.encode()).hexdigest()
_FAKE_TENANT = TenantDocument(
    tenant_id="test-tenant",
    name="test-tenant",
    api_key_hash=_KEY_HASH,
    rate_limit_rpm=2,
    created_at=datetime.now(UTC),
)


def _make_tenant_doc(tenant: TenantDocument) -> dict:
    return {
        "tenant_id": tenant.tenant_id,
        "name": tenant.name,
        "api_key_hash": tenant.api_key_hash,
        "rate_limit_rpm": tenant.rate_limit_rpm,
        "created_at": tenant.created_at,
    }


def _build_app(tenant: TenantDocument = _FAKE_TENANT) -> FastAPI:
    from app.core.auth import AuthMiddleware
    from app.core.middleware import RequestIDMiddleware
    from app.core.rate_limiter import RateLimiterMiddleware

    mini_app = FastAPI()

    @mini_app.get("/protected")
    async def protected_route() -> JSONResponse:
        return JSONResponse({"ok": True})

    @mini_app.get("/v1/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    mini_app.add_middleware(RateLimiterMiddleware)
    mini_app.add_middleware(AuthMiddleware)
    mini_app.add_middleware(RequestIDMiddleware)

    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=_make_tenant_doc(tenant))
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    mini_app.state.motor_client = mock_motor

    return mini_app


@pytest.fixture(autouse=True)
def clear_counters() -> Generator[None, None, None]:
    rl_module._counters.clear()
    yield
    rl_module._counters.clear()


@pytest.fixture
def rate_limit_app() -> FastAPI:
    return _build_app()


@pytest.mark.asyncio
async def test_below_limit_passes(rate_limit_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-API-Key": _RAW_KEY})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_over_limit_returns_429(rate_limit_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        for _ in range(_FAKE_TENANT.rate_limit_rpm):
            await client.get("/protected", headers={"X-API-Key": _RAW_KEY})
        response = await client.get("/protected", headers={"X-API-Key": _RAW_KEY})
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_health_not_rate_limited(rate_limit_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        for _ in range(10):
            response = await client.get("/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_expired_window_resets_counter(rate_limit_app: FastAPI) -> None:
    rl_module._counters["test-tenant"] = (time.monotonic() - 61.0, 999)
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-API-Key": _RAW_KEY})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_default_rate_limit_applied_when_rpm_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    zero_rpm_tenant = TenantDocument(
        tenant_id="zero-tenant",
        name="zero-tenant",
        api_key_hash=_KEY_HASH,
        rate_limit_rpm=0,
        created_at=datetime.now(UTC),
    )
    app = _build_app(zero_rpm_tenant)
    from app.core.config import get_settings

    settings = get_settings()
    default_limit = settings.default_rate_limit_rpm

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(default_limit):
            r = await client.get("/protected", headers={"X-API-Key": _RAW_KEY})
            assert r.status_code == 200
        response = await client.get("/protected", headers={"X-API-Key": _RAW_KEY})
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_default_rate_limit_applied_when_rpm_none(monkeypatch: pytest.MonkeyPatch) -> None:
    none_rpm_tenant = TenantDocument(
        tenant_id="none-tenant",
        name="none-tenant",
        api_key_hash=_KEY_HASH,
        rate_limit_rpm=None,
        created_at=datetime.now(UTC),
    )
    app = _build_app(none_rpm_tenant)
    from app.core.config import get_settings

    settings = get_settings()
    default_limit = settings.default_rate_limit_rpm

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(default_limit):
            r = await client.get("/protected", headers={"X-API-Key": _RAW_KEY})
            assert r.status_code == 200
        response = await client.get("/protected", headers={"X-API-Key": _RAW_KEY})
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_unauthenticated_request_not_rate_limited(rate_limit_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        response = await client.get("/protected")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_independent_counters_per_tenant() -> None:
    tenant_a = TenantDocument(
        tenant_id="tenant-a",
        name="tenant-a",
        api_key_hash=hashlib.sha256(b"key-a").hexdigest(),
        rate_limit_rpm=2,
        created_at=datetime.now(UTC),
    )
    tenant_b = TenantDocument(
        tenant_id="tenant-b",
        name="tenant-b",
        api_key_hash=hashlib.sha256(b"key-b").hexdigest(),
        rate_limit_rpm=2,
        created_at=datetime.now(UTC),
    )

    from app.core.auth import AuthMiddleware
    from app.core.middleware import RequestIDMiddleware
    from app.core.rate_limiter import RateLimiterMiddleware

    mini_app = FastAPI()

    @mini_app.get("/protected")
    async def protected_route() -> JSONResponse:
        return JSONResponse({"ok": True})

    mini_app.add_middleware(RateLimiterMiddleware)
    mini_app.add_middleware(AuthMiddleware)
    mini_app.add_middleware(RequestIDMiddleware)

    def _make_mock_for(tenant: TenantDocument) -> MagicMock:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=_make_tenant_doc(tenant))
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_motor = MagicMock()
        mock_motor.__getitem__ = MagicMock(return_value=mock_db)
        return mock_motor

    # Exhaust tenant_a's limit
    mini_app.state.motor_client = _make_mock_for(tenant_a)
    async with AsyncClient(transport=ASGITransport(app=mini_app), base_url="http://test") as client:
        for _ in range(tenant_a.rate_limit_rpm):
            await client.get("/protected", headers={"X-API-Key": "key-a"})
        r_a = await client.get("/protected", headers={"X-API-Key": "key-a"})
    assert r_a.status_code == 429

    # tenant_b should still be allowed (independent counter)
    mini_app.state.motor_client = _make_mock_for(tenant_b)
    async with AsyncClient(transport=ASGITransport(app=mini_app), base_url="http://test") as client:
        r_b = await client.get("/protected", headers={"X-API-Key": "key-b"})
    assert r_b.status_code == 200
