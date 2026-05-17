from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from app.core.errors import TokenBudgetExceededError
from app.models.agent import AgentDocument
from app.models.query import QueryRequest, QueryResponse
from app.models.tenant import TenantDocument
from app.services import query_service


def _make_agent(top_k: int = 5) -> AgentDocument:
    return AgentDocument.model_construct(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=top_k,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        embedding_provider_mismatch=False,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _stub_response() -> QueryResponse:
    return QueryResponse(answer="ok", confidence=0.5, citations=[], latency_ms=3)


def _tenant_with_budget(budget: int | None) -> TenantDocument:
    return TenantDocument.model_construct(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash="hash",
        rate_limit_rpm=60,
        role="agent_owner",
        monthly_token_budget=budget,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_handle_query_raises_when_budget_exceeded_before_pipeline() -> None:
    req = QueryRequest(query="hello")
    bg = BackgroundTasks()

    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=_make_agent()),
    ), patch(
        "app.services.query_service.query_cost_dao.get_monthly_token_total",
        AsyncMock(return_value=1000),
    ) as monthly_total_mock, patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as pipeline_mock, pytest.raises(TokenBudgetExceededError):
        await query_service.handle_query(
            "agent-1",
            "tenant-1",
            "hash",
            req,
            bg,
            tenant=_tenant_with_budget(1000),
        )

    monthly_total_mock.assert_awaited_once()
    pipeline_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_query_calls_pipeline_when_budget_available() -> None:
    req = QueryRequest(query="hello")
    bg = BackgroundTasks()

    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=_make_agent()),
    ), patch(
        "app.services.query_service.query_cost_dao.get_monthly_token_total",
        AsyncMock(return_value=999),
    ) as monthly_total_mock, patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as pipeline_mock, patch(
        "app.services.query_service.audit_service.write_audit_log",
        AsyncMock(),
    ), patch(
        "app.services.query_service.conversation_dao.create_session",
        AsyncMock(return_value=SimpleNamespace(session_id="session-1")),
    ), patch(
        "app.services.query_service.conversation_dao.append_messages",
        AsyncMock(),
    ):
        response = await query_service.handle_query(
            "agent-1",
            "tenant-1",
            "hash",
            req,
            bg,
            tenant=_tenant_with_budget(1000),
        )

    assert response.answer == "ok"
    monthly_total_mock.assert_awaited_once()
    pipeline_mock.assert_awaited_once()
