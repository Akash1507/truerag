import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.utils.pagination import encode_cursor

FAKE_API_KEY = "test-key-value"
FAKE_CALLER = {
    "tenant_id": "caller-id",
    "name": "caller",
    "api_key_hash": hashlib.sha256(FAKE_API_KEY.encode()).hexdigest(),
    "rate_limit_rpm": 60,
    "created_at": datetime.now(UTC),
}


def make_app_with_mock_db(
    find_one_return: dict | None = None,
    insert_one_return: object | None = None,
) -> FastAPI:
    app = create_app()
    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=find_one_return)
    mock_collection.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="abc")
        if insert_one_return is None
        else insert_one_return
    )
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = MagicMock()
    return app


def make_authed_app_for_list(tenant_docs: list[dict]) -> FastAPI:
    app = create_app()
    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=FAKE_CALLER)

    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=tenant_docs)
    mock_collection.find = MagicMock(return_value=mock_cursor)

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)

    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = MagicMock()
    return app


def make_authed_app_for_delete(
    tenant_doc: dict | None,
    agent_docs: list[dict] | None = None,
) -> FastAPI:
    if agent_docs is None:
        agent_docs = []

    app = create_app()
    mock_collection = MagicMock()

    def find_one_side_effect(query: dict) -> dict | None:
        if "api_key_hash" in query:
            return FAKE_CALLER
        if "tenant_id" in query:
            return tenant_doc
        return None

    mock_collection.find_one = AsyncMock(side_effect=find_one_side_effect)

    mock_agent_cursor = MagicMock()
    mock_agent_cursor.to_list = AsyncMock(return_value=agent_docs)
    mock_collection.find = MagicMock(return_value=mock_agent_cursor)
    mock_collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=len(agent_docs)))
    mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)

    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = MagicMock()
    return app


# ---------------------------------------------------------------------------
# POST /v1/tenants tests (existing, kept intact)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_tenant_success() -> None:
    app = make_app_with_mock_db(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/tenants", json={"name": "acme"})

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"]
    assert body["name"] == "acme"
    assert body["api_key"]
    assert isinstance(body["rate_limit_rpm"], int)
    assert body["created_at"]


@pytest.mark.asyncio
async def test_register_tenant_api_key_is_raw_not_hash() -> None:
    app = make_app_with_mock_db(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/tenants", json={"name": "acme"})

    assert response.status_code == 201
    api_key = response.json()["api_key"]
    assert len(api_key) == 43
    assert not all(c in "0123456789abcdef" for c in api_key)


@pytest.mark.asyncio
async def test_register_tenant_duplicate_name_returns_409() -> None:
    existing_doc = {
        "tenant_id": "existing-id",
        "name": "acme",
        "api_key_hash": "somehash",
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC).isoformat(),
    }
    app = make_app_with_mock_db(find_one_return=existing_doc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/tenants", json={"name": "acme"})

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "TENANT_ALREADY_EXISTS"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_register_tenant_missing_name_returns_422() -> None:
    app = make_app_with_mock_db(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/tenants", json={})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_tenant_empty_name_returns_422() -> None:
    app = make_app_with_mock_db(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/tenants", json={"name": ""})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_tenant_name_too_long_returns_422() -> None:
    app = make_app_with_mock_db(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/tenants", json={"name": "a" * 101})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_tenant_name_invalid_chars_returns_422() -> None:
    app = make_app_with_mock_db(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/tenants", json={"name": "bad name!"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_tenant_no_auth_key_required() -> None:
    """POST /v1/tenants must succeed without X-API-Key header."""
    app = make_app_with_mock_db(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/tenants",
            json={"name": "bootstrap-tenant"},
            headers={},
        )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_register_tenant_response_has_no_api_key_hash() -> None:
    """The response body must not expose api_key_hash."""
    app = make_app_with_mock_db(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/tenants", json={"name": "acme"})

    assert response.status_code == 201
    body = response.json()
    assert "api_key_hash" not in body


@pytest.mark.asyncio
async def test_register_tenant_api_key_hash_matches_sha256() -> None:
    """Verify internally that the returned api_key hashes to SHA-256."""
    from unittest.mock import patch

    captured: dict = {}

    original_create = None

    async def spy_create_tenant(name: str, db: object) -> object:
        result = await original_create(name, db)  # type: ignore[misc]
        captured["tenant"] = result[0]
        captured["raw_key"] = result[1]
        return result

    import app.services.tenant_service as svc

    original_create = svc.create_tenant  # type: ignore[assignment]

    app_instance = make_app_with_mock_db(find_one_return=None)
    with patch.object(svc, "create_tenant", side_effect=spy_create_tenant):
        async with AsyncClient(
            transport=ASGITransport(app=app_instance), base_url="http://test"
        ) as client:
            response = await client.post("/v1/tenants", json={"name": "verify-hash"})

    assert response.status_code == 201
    raw_key = captured["raw_key"]
    tenant = captured["tenant"]
    expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    assert tenant.api_key_hash == expected_hash
    assert response.json()["api_key"] == raw_key


# ---------------------------------------------------------------------------
# GET /v1/tenants tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tenants_empty_platform() -> None:
    app = make_authed_app_for_list([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/tenants", headers={"X-API-Key": FAKE_API_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_tenants_single_tenant() -> None:
    oid = ObjectId()
    tenant_doc = {
        "_id": oid,
        "tenant_id": "t1",
        "name": "acme",
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC),
    }
    app = make_authed_app_for_list([tenant_doc])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/tenants", headers={"X-API-Key": FAKE_API_KEY})

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["tenant_id"] == "t1"
    assert body["items"][0]["name"] == "acme"
    assert "api_key_hash" not in body["items"][0]
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_tenants_cursor_pagination_returns_next_cursor() -> None:
    """When DB returns limit+1 docs, response includes next_cursor."""
    limit = 2
    oids = [ObjectId() for _ in range(limit + 1)]
    tenant_docs = [
        {
            "_id": oid,
            "tenant_id": f"t{i}",
            "name": f"tenant-{i}",
            "rate_limit_rpm": 60,
            "created_at": datetime.now(UTC),
        }
        for i, oid in enumerate(oids)
    ]
    app = make_authed_app_for_list(tenant_docs)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/tenants?limit={limit}",
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == limit
    assert body["next_cursor"] is not None
    # next_cursor should encode the last doc's _id (oids[limit-1])
    expected_cursor = encode_cursor(oids[limit - 1])
    assert body["next_cursor"] == expected_cursor


@pytest.mark.asyncio
async def test_list_tenants_no_api_key_returns_401() -> None:
    app = make_authed_app_for_list([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/tenants")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_tenants_invalid_cursor_returns_400() -> None:
    app = make_authed_app_for_list([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/tenants?cursor=not-a-valid-cursor",
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_tenants_limit_above_max_returns_422() -> None:
    app = make_authed_app_for_list([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/tenants?limit=101",
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /v1/tenants/{tenant_id} tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_tenant_success_no_agents() -> None:
    tenant_doc = {
        "_id": ObjectId(),
        "tenant_id": FAKE_CALLER["tenant_id"],
        "name": "acme",
        "api_key_hash": "hash",
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC),
    }
    app = make_authed_app_for_delete(tenant_doc=tenant_doc, agent_docs=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/v1/tenants/{FAKE_CALLER['tenant_id']}", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_delete_tenant_not_found_returns_404() -> None:
    app = make_authed_app_for_delete(tenant_doc=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/v1/tenants/{FAKE_CALLER['tenant_id']}", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "TENANT_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_tenant_cross_tenant_returns_403() -> None:
    app = make_authed_app_for_delete(tenant_doc=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            "/v1/tenants/other-tenant-id", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_delete_tenant_no_api_key_returns_401() -> None:
    app = make_authed_app_for_delete(tenant_doc=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/v1/tenants/t1")

    assert response.status_code == 401
