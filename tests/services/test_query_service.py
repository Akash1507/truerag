from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

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
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=stub),
    ) as mock_pipeline, patch("app.services.query_service.audit_service.write_audit_log", AsyncMock()):
        result = await query_service.handle_query("agent-1", "tenant-1", "hash", req, bg)

    assert result == stub
    mock_pipeline.assert_awaited_once_with(
        query="hello",
        top_k=3,
        agent=agent,
        filters={"document_id": "doc-1"},
        output_format=None,
    )


@pytest.mark.asyncio
async def test_handle_query_top_k_fallback_to_agent_default() -> None:
    req = QueryRequest(query="hello", top_k=None)
    agent = _make_agent(top_k=5)
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as mock_pipeline, patch("app.services.query_service.audit_service.write_audit_log", AsyncMock()):
        await query_service.handle_query("agent-1", "tenant-1", "hash", req, bg)

    mock_pipeline.assert_awaited_once_with(query="hello", top_k=5, agent=agent, filters=None, output_format=None)


@pytest.mark.asyncio
async def test_handle_query_forbidden_propagates() -> None:
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(side_effect=ForbiddenError("forbidden")),
    ), pytest.raises(ForbiddenError):
        await query_service.handle_query("agent-1", "tenant-1", "hash", QueryRequest(query="q"), bg)


@pytest.mark.asyncio
async def test_handle_query_not_found_propagates() -> None:
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(side_effect=AgentNotFoundError("not found")),
    ), pytest.raises(AgentNotFoundError):
        await query_service.handle_query("agent-1", "tenant-1", "hash", QueryRequest(query="q"), bg)


@pytest.mark.asyncio
async def test_handle_query_passes_filters_to_pipeline() -> None:
    req = QueryRequest(query="hello", top_k=3, filters={"document_id": "doc-1"})
    agent = _make_agent(top_k=5)
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as mock_pipeline, patch("app.services.query_service.audit_service.write_audit_log", AsyncMock()):
        await query_service.handle_query("agent-1", "tenant-1", "hash", req, bg)

    mock_pipeline.assert_awaited_once_with(
        query="hello",
        top_k=3,
        agent=agent,
        filters={"document_id": "doc-1"},
        output_format=None,
    )


@pytest.mark.asyncio
async def test_handle_query_passes_none_filters_when_omitted() -> None:
    req = QueryRequest(query="hello", top_k=3)
    agent = _make_agent(top_k=5)
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as mock_pipeline, patch("app.services.query_service.audit_service.write_audit_log", AsyncMock()):
        await query_service.handle_query("agent-1", "tenant-1", "hash", req, bg)

    mock_pipeline.assert_awaited_once_with(query="hello", top_k=3, agent=agent, filters=None, output_format=None)


@pytest.mark.asyncio
async def test_handle_query_passes_output_format_to_pipeline() -> None:
    req = QueryRequest(query="hello", top_k=3, output_format="json")
    agent = _make_agent(top_k=5)
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=agent),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=_stub_response()),
    ) as mock_pipeline, patch("app.services.query_service.audit_service.write_audit_log", AsyncMock()):
        await query_service.handle_query("agent-1", "tenant-1", "hash", req, bg)

    mock_pipeline.assert_awaited_once_with(
        query="hello",
        top_k=3,
        agent=agent,
        filters=None,
        output_format="json",
    )


@pytest.mark.asyncio
async def test_handle_query_schedules_audit_background_task() -> None:
    mock_response = QueryResponse(answer="ans", confidence=0.7, citations=[], latency_ms=100)
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=_make_agent()),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=mock_response),
    ):
        await query_service.handle_query(
            agent_id="agent-1",
            tenant_id="tenant-1",
            api_key_hash="testhash",
            request=QueryRequest(query="hello"),
            background_tasks=bg,
        )
    assert len(bg.tasks) == 1


@pytest.mark.asyncio
async def test_handle_query_audit_uses_caller_api_key_hash() -> None:
    mock_response = QueryResponse(answer="ans", confidence=0.5, citations=[], latency_ms=50)
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=_make_agent()),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=mock_response),
    ):
        await query_service.handle_query(
            agent_id="agent-1",
            tenant_id="tenant-1",
            api_key_hash="my-sha256-hash",
            request=QueryRequest(query="test query"),
            background_tasks=bg,
        )
    task_kwargs = bg.tasks[0].kwargs
    assert task_kwargs["api_key_hash"] == "my-sha256-hash"
    assert task_kwargs["response_confidence"] == 0.5
    assert task_kwargs["cache_hit"] is False


@pytest.mark.asyncio
async def test_handle_query_audit_scheduled_even_on_pipeline_error() -> None:
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=_make_agent()),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(side_effect=RuntimeError("pipeline down")),
    ), pytest.raises(RuntimeError):
        await query_service.handle_query(
            agent_id="agent-1",
            tenant_id="tenant-1",
            api_key_hash="hash",
            request=QueryRequest(query="test"),
            background_tasks=bg,
        )
    assert len(bg.tasks) == 1
    assert bg.tasks[0].kwargs["response_confidence"] == 0.0


@pytest.mark.asyncio
async def test_handle_query_audit_query_hash_is_sha256_of_scrubbed() -> None:
    import hashlib

    mock_response = QueryResponse(answer="ans", confidence=0.3, citations=[], latency_ms=20)
    bg = BackgroundTasks()
    with patch(
        "app.services.query_service.agent_service.get_agent",
        AsyncMock(return_value=_make_agent()),
    ), patch(
        "app.services.query_service.run_query_pipeline",
        AsyncMock(return_value=mock_response),
    ), patch("app.services.query_service.scrub_pii", return_value="scrubbed text") as mock_scrub:
        await query_service.handle_query(
            agent_id="a",
            tenant_id="t",
            api_key_hash="h",
            request=QueryRequest(query="raw pii text"),
            background_tasks=bg,
        )
    mock_scrub.assert_called_once_with("raw pii text")
    expected_hash = hashlib.sha256("scrubbed text".encode()).hexdigest()
    assert bg.tasks[0].kwargs["query_hash"] == expected_hash
