import hashlib
from datetime import UTC, datetime
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import agents, tenants
from app.core.auth import AuthMiddleware
from app.core.errors import TrueRAGError
from app.core.exception_handlers import generic_exception_handler, truerag_exception_handler
from app.core.middleware import RequestIDMiddleware
from app.models.agent import AgentCreateResponse
from app.models.tenant import TenantDocument, TenantListResponse


AGENT_CREATE_BODY = {
    "name": "agent-rbac",
    "chunking_strategy": "fixed_size",
    "vector_store": "pgvector",
    "embedding_provider": "openai",
    "llm_provider": "anthropic",
    "retrieval_mode": "dense",
    "reranker": "none",
    "top_k": 5,
    "semantic_cache_enabled": False,
}


def _tenant(role: str, api_key: str = "key") -> TenantDocument:
    return TenantDocument.model_construct(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
        rate_limit_rpm=60,
        role=role,  # type: ignore[arg-type]
        created_at=datetime.now(UTC),
    )


def _agent_response() -> AgentCreateResponse:
    now = datetime.now(UTC)
    return AgentCreateResponse(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-rbac",
        chunking_strategy="fixed_size",
        chunk_size=512,
        chunk_overlap=50,
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        query_rewrite=False,
        hallucination_check_enabled=False,
        rerank_pool_size=20,
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        context_window_tokens=4000,
        faithfulness_threshold=0.6,
        status="active",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def test_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(TrueRAGError, truerag_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(agents.router, prefix="/v1/agents")
    app.include_router(tenants.router, prefix="/v1/tenants")
    return app


@pytest.fixture
async def api_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_reader_forbidden_on_post_agents(api_client: AsyncClient) -> None:
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant("reader"))), patch(
        "app.api.v1.agents.agent_service.create",
        AsyncMock(return_value=_agent_response()),
    ) as create_mock:
        response = await api_client.post(
            "/v1/agents",
            json=AGENT_CREATE_BODY,
            headers={"X-API-Key": "key"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert response.json()["error"]["message"] == "Reader role cannot perform write operations"
    create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_owner_forbidden_on_get_tenants(api_client: AsyncClient) -> None:
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant("agent_owner"))), patch(
        "app.api.v1.tenants.tenant_service.list",
        AsyncMock(return_value=TenantListResponse(items=[], next_cursor=None)),
    ) as list_mock:
        response = await api_client.get("/v1/tenants", headers={"X-API-Key": "key"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    list_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_allowed_for_post_agents_and_get_tenants(api_client: AsyncClient) -> None:
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant("admin"))), patch(
        "app.api.v1.agents.agent_service.create",
        AsyncMock(return_value=_agent_response()),
    ), patch(
        "app.api.v1.tenants.tenant_service.list",
        AsyncMock(return_value=TenantListResponse(items=[], next_cursor=None)),
    ):
        create_response = await api_client.post(
            "/v1/agents",
            json=AGENT_CREATE_BODY,
            headers={"X-API-Key": "key"},
        )
        list_response = await api_client.get("/v1/tenants", headers={"X-API-Key": "key"})

    assert create_response.status_code == 201
    assert list_response.status_code == 200
