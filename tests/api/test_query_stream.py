import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import StreamingResponse

from app.models.tenant import TenantDocument


def _tenant(api_key: str = "key") -> TenantDocument:
    return TenantDocument.model_construct(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
        rate_limit_rpm=60,
        role="admin",
        monthly_token_budget=None,
        created_at=datetime.now(UTC),
    )


async def _stream_body():
    yield 'data: {"type":"token","token":"hello"}\n\n'
    yield 'data: {"type":"done","confidence":1.0,"citations":[],"latency_ms":5}\n\n'
    yield "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_query_route_stream_returns_sse(client) -> None:  # type: ignore[no-untyped-def]
    stream_response = StreamingResponse(content=_stream_body(), media_type="text/event-stream")

    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.query.query_service.handle_query",
        AsyncMock(return_value=stream_response),
    ):
        async with client.stream(
            "POST",
            "/v1/agents/agent-1/query",
            json={"query": "hello", "stream": True},
            headers={"X-API-Key": "key"},
        ) as response:
            body = ""
            async for part in response.aiter_text():
                body += part

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type":"token","token":"hello"}' in body
    assert "data: [DONE]" in body
