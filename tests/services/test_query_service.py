from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import AgentNotFoundError, ForbiddenError
from app.models.agent import AgentDocument
from app.models.query import QueryRequest, QueryResponse
from app.services import query_service


def _make_agent(top_k: int = 5) -> AgentDocument:
    return AgentDocument(
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
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _stub_response() -> QueryResponse:
    return QueryResponse(answer="ok", confidence=0.5, citations=[], latency_ms=3)


@pytest.mark.asyncio
async def test_handle_query_happy_path_calls_pipeline() -> None:
    req = QueryRequest(query="hello", top_k=3, filters={"document_id": "doc-1"})
    agent = _make_agent(top_k=5)
    stub = _stub_response()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=stub),
    ) as mock_pipeline:
        result = await query_service.handle_query("agent-1", "tenant-1", req)

    assert result == stub
    mock_pipeline.assert_awaited_once_with(
        query="hello",
        top_k=3,
        agent=agent,
        filters={"document_id": "doc-1"},
    )


@pytest.mark.asyncio
async def test_handle_query_top_k_fallback_to_agent_default() -> None:
    req = QueryRequest(query="hello", top_k=None)
    agent = _make_agent(top_k=5)
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as mock_pipeline:
        await query_service.handle_query("agent-1", "tenant-1", req)

    mock_pipeline.assert_awaited_once_with(query="hello", top_k=5, agent=agent, filters=None)


@pytest.mark.asyncio
async def test_handle_query_forbidden_propagates() -> None:
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(side_effect=ForbiddenError("forbidden")),
    ), pytest.raises(ForbiddenError):
        await query_service.handle_query("agent-1", "tenant-1", QueryRequest(query="q"))


@pytest.mark.asyncio
async def test_handle_query_not_found_propagates() -> None:
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(side_effect=AgentNotFoundError("not found")),
    ), pytest.raises(AgentNotFoundError):
        await query_service.handle_query("agent-1", "tenant-1", QueryRequest(query="q"))


@pytest.mark.asyncio
async def test_handle_query_passes_filters_to_pipeline() -> None:
    req = QueryRequest(query="hello", top_k=3, filters={"document_id": "doc-1"})
    agent = _make_agent(top_k=5)
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as mock_pipeline:
        await query_service.handle_query("agent-1", "tenant-1", req)

    mock_pipeline.assert_awaited_once_with(
        query="hello",
        top_k=3,
        agent=agent,
        filters={"document_id": "doc-1"},
    )


@pytest.mark.asyncio
async def test_handle_query_passes_none_filters_when_omitted() -> None:
    req = QueryRequest(query="hello", top_k=3)
    agent = _make_agent(top_k=5)
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as mock_pipeline:
        await query_service.handle_query("agent-1", "tenant-1", req)

    mock_pipeline.assert_awaited_once_with(query="hello", top_k=3, agent=agent, filters=None)
