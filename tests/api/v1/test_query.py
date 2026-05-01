import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import AgentNotFoundError, ForbiddenError
from app.models.query import QueryResponse
from app.models.tenant import TenantDocument


def _tenant(api_key: str = "key") -> TenantDocument:
    return TenantDocument(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_query_route_happy_path(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.query.query_service.handle_query",
        AsyncMock(
            return_value=QueryResponse(
                answer="stub",
                confidence=0.5,
                citations=[],
                latency_ms=7,
            )
        ),
    ):
        response = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "hello"},
            headers={"X-API-Key": "key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "stub"
    assert data["confidence"] == 0.5
    assert data["citations"] == []
    assert data["latency_ms"] == 7


@pytest.mark.asyncio
async def test_query_route_missing_auth_returns_401(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post("/v1/agents/agent-1/query", json={"query": "hello"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_query_route_cross_tenant_returns_403(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.query.query_service.handle_query",
        AsyncMock(side_effect=ForbiddenError("forbidden")),
    ):
        response = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "hello"},
            headers={"X-API-Key": "key"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_query_route_not_found_returns_404(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.query.query_service.handle_query",
        AsyncMock(side_effect=AgentNotFoundError("not found")),
    ):
        response = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "hello"},
            headers={"X-API-Key": "key"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_query_route_empty_query_returns_422(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())):
        response = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": ""},
            headers={"X-API-Key": "key"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_query_route_whitespace_only_query_returns_422(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())):
        response = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "   "},
            headers={"X-API-Key": "key"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_query_route_invalid_top_k_returns_422(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())):
        response = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "hello", "top_k": 0},
            headers={"X-API-Key": "key"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_query_route_accepts_filters_and_propagates(client) -> None:  # type: ignore[no-untyped-def]
    mock_handle_query = AsyncMock(
        return_value=QueryResponse(
            answer="stub",
            confidence=0.5,
            citations=[],
            latency_ms=7,
        )
    )
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.query.query_service.handle_query",
        mock_handle_query,
    ):
        response = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "hello", "filters": {"document_id": "doc-1"}},
            headers={"X-API-Key": "key"},
        )

    assert response.status_code == 200
    request_model = mock_handle_query.await_args.kwargs["request"]
    assert request_model.filters == {"document_id": "doc-1"}


@pytest.mark.asyncio
async def test_query_route_without_filters_defaults_to_none(client) -> None:  # type: ignore[no-untyped-def]
    mock_handle_query = AsyncMock(
        return_value=QueryResponse(
            answer="stub",
            confidence=0.5,
            citations=[],
            latency_ms=7,
        )
    )
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.query.query_service.handle_query",
        mock_handle_query,
    ):
        response = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "hello"},
            headers={"X-API-Key": "key"},
        )

    assert response.status_code == 200
    request_model = mock_handle_query.await_args.kwargs["request"]
    assert request_model.filters is None
