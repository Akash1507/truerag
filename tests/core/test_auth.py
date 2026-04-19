import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.auth import _hash_api_key, verify_tenant_ownership
from app.core.errors import NamespaceViolationError

# --- Unit tests for pure functions ---


def test_hash_api_key_deterministic() -> None:
    key = "test-api-key-123"
    expected = hashlib.sha256(key.encode()).hexdigest()
    assert _hash_api_key(key) == expected


def test_hash_api_key_different_keys_differ() -> None:
    assert _hash_api_key("key-a") != _hash_api_key("key-b")


def test_verify_tenant_ownership_same_tenant() -> None:
    verify_tenant_ownership("tenant-a", "tenant-a")  # no exception


def test_verify_tenant_ownership_different_tenant() -> None:
    with pytest.raises(NamespaceViolationError):
        verify_tenant_ownership("tenant-a", "tenant-b")


# --- Minimal test app fixture (avoids lifespan DB connections) ---


@pytest.fixture
def auth_test_app() -> FastAPI:
    from app.core.auth import AuthMiddleware
    from app.core.middleware import RequestIDMiddleware

    mini_app = FastAPI()

    @mini_app.get("/protected")
    async def protected_route() -> JSONResponse:
        return JSONResponse({"ok": True})

    @mini_app.get("/v1/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mini_app.get("/v1/ready")
    async def ready() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    mini_app.add_middleware(AuthMiddleware)
    mini_app.add_middleware(RequestIDMiddleware)

    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=None)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    mini_app.state.motor_client = mock_motor

    return mini_app


@pytest.fixture
def auth_test_app_with_tenant() -> FastAPI:
    from app.core.auth import AuthMiddleware
    from app.core.middleware import RequestIDMiddleware

    tenant_doc = {
        "tenant_id": "tenant-abc",
        "api_key_hash": _hash_api_key("valid-key"),
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC),
    }

    mini_app = FastAPI()

    @mini_app.get("/protected")
    async def protected_route() -> JSONResponse:
        return JSONResponse({"ok": True})

    mini_app.add_middleware(AuthMiddleware)
    mini_app.add_middleware(RequestIDMiddleware)

    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=tenant_doc)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    mini_app.state.motor_client = mock_motor

    return mini_app


# --- Integration tests through the middleware ---


@pytest.mark.asyncio
async def test_health_no_auth_required(auth_test_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_test_app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ready_no_auth_required(auth_test_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_test_app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/ready")
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(auth_test_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_test_app), base_url="http://test"
    ) as client:
        response = await client.get("/protected")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401(auth_test_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_test_app), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-API-Key": "bad-key"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_valid_api_key_passes_through(auth_test_app_with_tenant: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_test_app_with_tenant), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-API-Key": "valid-key"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
