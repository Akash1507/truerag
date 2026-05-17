import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse

from app.models.query import QueryResponse
from app.models.tenant import TenantDocument


def _tenant(api_key: str = "key") -> TenantDocument:
    return TenantDocument.model_construct(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
        rate_limit_rpm=60,
        role="admin",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_query_route_supports_multi_turn_with_same_session_id(client) -> None:  # type: ignore[no-untyped-def]
    first_response = QueryResponse(
        answer="First answer: alpha is the first point.",
        confidence=0.9,
        citations=[],
        latency_ms=12,
        session_id="session-123",
    )
    second_response = QueryResponse(
        answer="Follow-up: alpha means the first point from the previous answer.",
        confidence=0.9,
        citations=[],
        latency_ms=10,
        session_id="session-123",
    )

    handle_query = AsyncMock(
        side_effect=[
            JSONResponse(status_code=200, content=first_response.model_dump(mode="json")),
            JSONResponse(status_code=200, content=second_response.model_dump(mode="json")),
        ]
    )
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.query.query_service.handle_query",
        handle_query,
    ):
        first = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "Explain alpha"},
            headers={"X-API-Key": "key"},
        )
        second = await client.post(
            "/v1/agents/agent-1/query",
            json={"query": "What did you mean by alpha?", "session_id": "session-123"},
            headers={"X-API-Key": "key"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session_id"] == "session-123"
    assert second.json()["session_id"] == "session-123"
    assert "previous answer" in second.json()["answer"]

    first_request = handle_query.await_args_list[0].kwargs["request"]
    second_request = handle_query.await_args_list[1].kwargs["request"]
    assert first_request.session_id is None
    assert second_request.session_id == "session-123"
