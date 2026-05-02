from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.agent import AgentDocument
from app.models.tenant import TenantDocument


def _tenant() -> TenantDocument:
    return TenantDocument(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash="hash",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )


def _agent() -> AgentDocument:
    return AgentDocument(
        agent_id="507f1f77bcf86cd799439011",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=10,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_create_agent_route_uses_service() -> None:
    app = create_app()
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.agents.agent_service.create_agent",
        AsyncMock(return_value=_agent()),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/agents",
                json={
                    "name": "agent-1",
                    "chunking_strategy": "fixed_size",
                    "vector_store": "pgvector",
                    "embedding_provider": "openai",
                    "llm_provider": "anthropic",
                    "retrieval_mode": "dense",
                    "reranker": "none",
                    "top_k": 10,
                },
                headers={"X-API-Key": "key"},
            )

    assert response.status_code == 201
    assert response.json()["agent_id"] == "507f1f77bcf86cd799439011"


@pytest.mark.asyncio
async def test_create_agent_default_faithfulness_threshold() -> None:
    app = create_app()
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.agents.agent_service.create_agent",
        AsyncMock(return_value=_agent()),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/agents",
                json={
                    "name": "agent-1",
                    "chunking_strategy": "fixed_size",
                    "vector_store": "pgvector",
                    "embedding_provider": "openai",
                    "llm_provider": "anthropic",
                    "retrieval_mode": "dense",
                    "reranker": "none",
                    "top_k": 10,
                },
                headers={"X-API-Key": "key"},
            )
    assert response.status_code == 201
    assert response.json()["faithfulness_threshold"] == 0.6


@pytest.mark.asyncio
async def test_create_agent_custom_faithfulness_threshold() -> None:
    app = create_app()
    custom = _agent()
    custom.faithfulness_threshold = 0.75
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch(
        "app.api.v1.agents.agent_service.create_agent",
        AsyncMock(return_value=custom),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/agents",
                json={
                    "name": "agent-1",
                    "chunking_strategy": "fixed_size",
                    "vector_store": "pgvector",
                    "embedding_provider": "openai",
                    "llm_provider": "anthropic",
                    "retrieval_mode": "dense",
                    "reranker": "none",
                    "top_k": 10,
                    "faithfulness_threshold": 0.75,
                },
                headers={"X-API-Key": "key"},
            )
    assert response.status_code == 201
    assert response.json()["faithfulness_threshold"] == 0.75
