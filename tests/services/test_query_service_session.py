from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from app.core.errors import ForbiddenError, SessionExpiredError
from app.models.agent import AgentDocument
from app.models.conversation import ConversationMessage, ConversationSession
from app.models.query import QueryRequest, QueryResponse
from app.services.query_service import QueryService


def _agent() -> AgentDocument:
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
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        embedding_provider_mismatch=False,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _service(conversation_dao: MagicMock, agent: AgentDocument) -> QueryService:
    agent_service = MagicMock()
    agent_service.get_agent = AsyncMock(return_value=agent)
    audit_service = MagicMock()
    audit_service.write_audit_log = AsyncMock()
    metrics_service = MagicMock()
    metrics_service.record_query = MagicMock()
    query_cost_dao = MagicMock()
    query_cost_dao.insert_one = AsyncMock()
    query_cost_dao.get_monthly_token_total = AsyncMock(return_value=0)
    return QueryService(
        agent_service_dep=agent_service,
        audit_service_dep=audit_service,
        metrics_service_dep=metrics_service,
        query_cost_dao_dep=query_cost_dao,
        conversation_dao_dep=conversation_dao,
    )


@pytest.mark.asyncio
async def test_handle_query_creates_session_when_missing() -> None:
    conversation_dao = MagicMock()
    conversation_dao.create_session = AsyncMock(
        return_value=ConversationSession.model_construct(
            session_id="session-1",
            agent_id="agent-1",
            tenant_id="tenant-1",
            messages=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    conversation_dao.get_session = AsyncMock()
    conversation_dao.append_messages = AsyncMock()
    service = _service(conversation_dao, _agent())

    with patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=QueryResponse(answer="ok", confidence=0.5, citations=[], latency_ms=5)),
    ) as pipeline:
        response = await service.handle_query(
            "agent-1",
            "tenant-1",
            "hash",
            QueryRequest(query="hello"),
            BackgroundTasks(),
        )

    assert isinstance(response, QueryResponse)
    assert response.session_id == "session-1"
    conversation_dao.create_session.assert_awaited_once_with(agent_id="agent-1", tenant_id="tenant-1")
    conversation_dao.append_messages.assert_awaited_once()
    assert pipeline.await_args.kwargs["conversation_history"] is None


@pytest.mark.asyncio
async def test_handle_query_continues_existing_session_with_history() -> None:
    history = [
        ConversationMessage(role="user", content="u1", timestamp=datetime.now(UTC)),
        ConversationMessage(role="assistant", content="a1", timestamp=datetime.now(UTC)),
    ]
    conversation_dao = MagicMock()
    conversation_dao.create_session = AsyncMock()
    conversation_dao.get_session = AsyncMock(
        return_value=ConversationSession.model_construct(
            session_id="session-1",
            agent_id="agent-1",
            tenant_id="tenant-1",
            messages=history,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    conversation_dao.append_messages = AsyncMock()
    service = _service(conversation_dao, _agent())

    with patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=QueryResponse(answer="ok", confidence=0.5, citations=[], latency_ms=5)),
    ) as pipeline:
        await service.handle_query(
            "agent-1",
            "tenant-1",
            "hash",
            QueryRequest(query="hello", session_id="session-1"),
            BackgroundTasks(),
        )

    conversation_dao.create_session.assert_not_called()
    conversation_dao.get_session.assert_awaited_once_with(
        session_id="session-1",
        agent_id="agent-1",
        tenant_id="tenant-1",
    )
    assert pipeline.await_args.kwargs["conversation_history"] == history


@pytest.mark.asyncio
async def test_handle_query_returns_403_for_cross_agent_or_tenant_session() -> None:
    conversation_dao = MagicMock()
    conversation_dao.create_session = AsyncMock()
    conversation_dao.get_session = AsyncMock(return_value=None)
    conversation_dao.append_messages = AsyncMock()
    service = _service(conversation_dao, _agent())

    with pytest.raises(ForbiddenError):
        await service.handle_query(
            "agent-1",
            "tenant-1",
            "hash",
            QueryRequest(query="hello", session_id="session-1"),
            BackgroundTasks(),
        )


@pytest.mark.asyncio
async def test_handle_query_returns_410_for_expired_session() -> None:
    conversation_dao = MagicMock()
    conversation_dao.create_session = AsyncMock()
    conversation_dao.get_session = AsyncMock(
        return_value=ConversationSession.model_construct(
            session_id="session-1",
            agent_id="agent-1",
            tenant_id="tenant-1",
            messages=[],
            created_at=datetime.now(UTC) - timedelta(days=2),
            updated_at=datetime.now(UTC) - timedelta(hours=25),
        )
    )
    conversation_dao.append_messages = AsyncMock()
    service = _service(conversation_dao, _agent())

    with pytest.raises(SessionExpiredError):
        await service.handle_query(
            "agent-1",
            "tenant-1",
            "hash",
            QueryRequest(query="hello", session_id="session-1"),
            BackgroundTasks(),
        )
