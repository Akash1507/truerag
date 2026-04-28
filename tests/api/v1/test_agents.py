import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app

FAKE_API_KEY = "test-agent-key"
FAKE_CALLER = {
    "tenant_id": "caller-tenant-id",
    "name": "caller",
    "api_key_hash": hashlib.sha256(FAKE_API_KEY.encode()).hexdigest(),
    "rate_limit_rpm": 60,
    "created_at": datetime.now(UTC),
}

FAKE_AGENT_DOC = {
    "agent_id": "507f1f77bcf86cd799439011",
    "tenant_id": FAKE_CALLER["tenant_id"],
    "name": "my-rag-agent",
    "chunking_strategy": "fixed_size",
    "vector_store": "pgvector",
    "embedding_provider": "openai",
    "llm_provider": "anthropic",
    "retrieval_mode": "dense",
    "reranker": "none",
    "top_k": 10,
    "semantic_cache_enabled": False,
    "semantic_cache_threshold": None,
    "status": "active",
    "created_at": datetime.now(UTC),
    "updated_at": datetime.now(UTC),
    "_id": ObjectId("507f1f77bcf86cd799439011"),
}

VALID_BODY = {
    "name": "my-rag-agent",
    "chunking_strategy": "fixed_size",
    "vector_store": "pgvector",
    "embedding_provider": "openai",
    "llm_provider": "anthropic",
    "retrieval_mode": "dense",
    "reranker": "none",
    "top_k": 10,
    "semantic_cache_enabled": False,
}


def make_authed_app(
    find_one_return: dict | None = None,
    find_return_list: list[dict] | None = None,
    agents_find_one_side_effect: list[dict | None] | None = None,
    update_one_return: MagicMock | None = None,
    documents_find_one_return: dict | None = None,
) -> FastAPI:
    app = create_app()

    mock_tenants = MagicMock()
    mock_tenants.find_one = AsyncMock(return_value=FAKE_CALLER)

    mock_agents = MagicMock()
    if agents_find_one_side_effect is not None:
        mock_agents.find_one = AsyncMock(side_effect=agents_find_one_side_effect)
    else:
        mock_agents.find_one = AsyncMock(return_value=find_one_return)
    mock_agents.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake-oid"))
    mock_agents.update_one = AsyncMock(return_value=update_one_return or MagicMock())
    mock_agents.delete_one = AsyncMock(return_value=MagicMock())
    mock_agents.delete_many = AsyncMock(return_value=MagicMock())

    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=find_return_list or [])
    mock_agents.find = MagicMock(return_value=mock_cursor)

    mock_documents = MagicMock()
    mock_documents.find_one = AsyncMock(return_value=documents_find_one_return)
    mock_documents.delete_one = AsyncMock(return_value=MagicMock())
    mock_documents.delete_many = AsyncMock(return_value=MagicMock())
    mock_doc_cursor = MagicMock()
    mock_doc_cursor.to_list = AsyncMock(return_value=[])
    mock_documents.find = MagicMock(return_value=mock_doc_cursor)

    def get_collection(name: str) -> MagicMock:
        if name == "agents":
            return mock_agents
        elif name == "documents":
            return mock_documents
        return mock_tenants

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=get_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = MagicMock()
    return app


@pytest.mark.asyncio
async def test_create_agent_201_happy_path() -> None:
    app = make_authed_app(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=VALID_BODY, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 201
    body = response.json()
    assert body["agent_id"]
    assert body["tenant_id"] == FAKE_CALLER["tenant_id"]
    assert body["name"] == VALID_BODY["name"]
    assert body["chunking_strategy"] == "fixed_size"
    assert body["status"] == "active"
    assert body["created_at"]
    assert body["updated_at"]


@pytest.mark.asyncio
async def test_create_agent_400_invalid_chunking_strategy() -> None:
    app = make_authed_app(find_one_return=None)
    body = {**VALID_BODY, "chunking_strategy": "unknown"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=body, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "AGENT_CONFIG_INVALID"
    assert "chunking_strategy" in data["error"]["message"]
    assert "supported values" in data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_create_agent_400_invalid_vector_store() -> None:
    app = make_authed_app(find_one_return=None)
    body = {**VALID_BODY, "vector_store": "redis"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=body, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_CONFIG_INVALID"


@pytest.mark.asyncio
async def test_create_agent_400_invalid_embedding_provider() -> None:
    app = make_authed_app(find_one_return=None)
    body = {**VALID_BODY, "embedding_provider": "mistral"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=body, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_CONFIG_INVALID"


@pytest.mark.asyncio
async def test_create_agent_409_duplicate_name() -> None:
    existing_agent = {
        "agent_id": "existing-id",
        "tenant_id": FAKE_CALLER["tenant_id"],
        "name": VALID_BODY["name"],
    }
    app = make_authed_app(find_one_return=existing_agent)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=VALID_BODY, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AGENT_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_create_agent_403_mismatched_tenant_id() -> None:
    app = make_authed_app(find_one_return=None)
    body = {**VALID_BODY, "tenant_id": "other-tenant"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=body, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_create_agent_401_no_api_key() -> None:
    app = make_authed_app(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/agents", json=VALID_BODY)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_agent_body_tenant_id_matches_caller_is_accepted() -> None:
    app = make_authed_app(find_one_return=None)
    body = {**VALID_BODY, "tenant_id": FAKE_CALLER["tenant_id"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=body, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_agent_400_cache_enabled_without_threshold() -> None:
    app = make_authed_app(find_one_return=None)
    body = {**VALID_BODY, "semantic_cache_enabled": True, "semantic_cache_threshold": None}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=body, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "AGENT_CONFIG_INVALID"
    assert "semantic_cache_threshold" in data["error"]["message"]


@pytest.mark.asyncio
async def test_create_agent_201_cache_enabled_with_threshold() -> None:
    app = make_authed_app(find_one_return=None)
    body = {**VALID_BODY, "semantic_cache_enabled": True, "semantic_cache_threshold": 0.85}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/agents", json=body, headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 201
    data = response.json()
    assert data["semantic_cache_enabled"] is True
    assert data["semantic_cache_threshold"] == 0.85


# ---------------------------------------------------------------------------
# GET /v1/agents/{agent_id} tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_200_happy_path() -> None:
    app = make_authed_app(find_one_return=FAKE_AGENT_DOC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == FAKE_AGENT_DOC["agent_id"]
    assert data["tenant_id"] == FAKE_CALLER["tenant_id"]
    assert data["name"] == FAKE_AGENT_DOC["name"]
    assert data["status"] == "active"
    assert data["created_at"]
    assert data["updated_at"]


@pytest.mark.asyncio
async def test_get_agent_403_different_tenant() -> None:
    doc = {**FAKE_AGENT_DOC, "tenant_id": "other-tenant-id"}
    app = make_authed_app(find_one_return=doc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_get_agent_404_not_found() -> None:
    app = make_authed_app(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/agents/nonexistent-id", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_agent_401_no_api_key() -> None:
    app = make_authed_app(find_one_return=FAKE_AGENT_DOC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/agents tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_200_empty() -> None:
    app = make_authed_app(find_return_list=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/agents", headers={"X-API-Key": FAKE_API_KEY})

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_agents_200_with_agents() -> None:
    app = make_authed_app(find_return_list=[FAKE_AGENT_DOC])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/agents", headers={"X-API-Key": FAKE_API_KEY})

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["agent_id"] == FAKE_AGENT_DOC["agent_id"]
    assert data["items"][0]["name"] == FAKE_AGENT_DOC["name"]
    assert data["items"][0]["status"] == "active"
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_agents_400_invalid_cursor() -> None:
    app = make_authed_app(find_return_list=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/agents?cursor=notbase64!!", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_list_agents_401_no_api_key() -> None:
    app = make_authed_app(find_return_list=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/agents")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /v1/agents/{agent_id}/config tests
# ---------------------------------------------------------------------------

UPDATED_AGENT_DOC = {
    **FAKE_AGENT_DOC,
    "chunking_strategy": "semantic",
    "updated_at": datetime.now(UTC),
}


@pytest.mark.asyncio
async def test_patch_agent_config_200_no_warnings() -> None:
    app = make_authed_app(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, FAKE_AGENT_DOC],
        documents_find_one_return=None,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/config",
            json={"vector_store": "pgvector"},
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["warnings"] == []


@pytest.mark.asyncio
async def test_patch_agent_config_400_cache_enabled_without_threshold() -> None:
    app = make_authed_app(agents_find_one_side_effect=[FAKE_AGENT_DOC])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/config",
            json={"semantic_cache_enabled": True},
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "AGENT_CONFIG_INVALID"
    assert "semantic_cache_threshold" in data["error"]["message"]


@pytest.mark.asyncio
async def test_patch_agent_config_200_can_clear_threshold_when_disabling_cache() -> None:
    existing_doc = {
        **FAKE_AGENT_DOC,
        "semantic_cache_enabled": True,
        "semantic_cache_threshold": 0.85,
    }
    updated_doc = {
        **existing_doc,
        "semantic_cache_enabled": False,
        "semantic_cache_threshold": None,
        "updated_at": datetime.now(UTC),
    }
    app = make_authed_app(agents_find_one_side_effect=[existing_doc, updated_doc])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/agents/{existing_doc['agent_id']}/config",
            json={"semantic_cache_enabled": False, "semantic_cache_threshold": None},
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["semantic_cache_enabled"] is False
    assert data["semantic_cache_threshold"] is None
    assert data["warnings"] == []


@pytest.mark.asyncio
async def test_patch_agent_config_200_chunking_warning() -> None:
    app = make_authed_app(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, UPDATED_AGENT_DOC],
        documents_find_one_return={"_id": "some-doc"},
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/config",
            json={"chunking_strategy": "semantic"},
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["warnings"]) == 1
    assert "fixed_size" in data["warnings"][0]
    assert "Re-ingestion" in data["warnings"][0]


@pytest.mark.asyncio
async def test_patch_agent_config_200_embedding_warning() -> None:
    updated = {**FAKE_AGENT_DOC, "embedding_provider": "cohere", "updated_at": datetime.now(UTC)}
    app = make_authed_app(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, updated],
        documents_find_one_return={"_id": "some-doc"},
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/config",
            json={"embedding_provider": "cohere"},
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["warnings"]) == 1
    assert "openai" in data["warnings"][0]
    assert "cohere" in data["warnings"][0]


@pytest.mark.asyncio
async def test_patch_agent_config_400_invalid_value() -> None:
    app = make_authed_app(agents_find_one_side_effect=[FAKE_AGENT_DOC])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/config",
            json={"chunking_strategy": "bad"},
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_CONFIG_INVALID"


@pytest.mark.asyncio
async def test_patch_agent_config_404_not_found() -> None:
    app = make_authed_app(agents_find_one_side_effect=[None])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            "/v1/agents/nonexistent-id/config",
            json={"vector_store": "qdrant"},
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_patch_agent_config_401_no_api_key() -> None:
    app = make_authed_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/config",
            json={"vector_store": "qdrant"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_agent_config_422_unknown_field() -> None:
    app = make_authed_app(agents_find_one_side_effect=[FAKE_AGENT_DOC])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/config",
            json={"vectorstore": "pgvector"},
            headers={"X-API-Key": FAKE_API_KEY},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /v1/agents/{agent_id} tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_agent_204_success() -> None:
    app = make_authed_app(find_one_return=FAKE_AGENT_DOC)
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(
                f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}", headers={"X-API-Key": FAKE_API_KEY}
            )

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_delete_agent_404_not_found() -> None:
    app = make_authed_app(find_one_return=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            "/v1/agents/nonexistent-id", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_agent_403_wrong_tenant() -> None:
    doc = {**FAKE_AGENT_DOC, "tenant_id": "other"}
    app = make_authed_app(find_one_return=doc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}", headers={"X-API-Key": FAKE_API_KEY}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_delete_agent_401_no_api_key() -> None:
    app = make_authed_app(find_one_return=FAKE_AGENT_DOC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}")

    assert response.status_code == 401
