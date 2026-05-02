from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.agent import AgentDocument
from app.pipelines.query.router import route_query


def _make_agent() -> AgentDocument:
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
        query_rewrite=False,
        rerank_pool_size=20,
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_route_query_returns_retrieval() -> None:
    agent = _make_agent()
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="retrieval")
    mock_llm_cls = MagicMock(return_value=mock_llm)

    with patch("app.pipelines.query.router.LLM_REGISTRY", {"anthropic": mock_llm_cls}):
        route = await route_query("query", agent, "req-1", "tenant-1")

    assert route == "retrieval"


@pytest.mark.asyncio
async def test_route_query_returns_direct() -> None:
    agent = _make_agent()
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=" direct ")
    mock_llm_cls = MagicMock(return_value=mock_llm)

    with patch("app.pipelines.query.router.LLM_REGISTRY", {"anthropic": mock_llm_cls}):
        route = await route_query("query", agent, "req-1", "tenant-1")

    assert route == "direct"


@pytest.mark.asyncio
async def test_route_query_unexpected_value_defaults_to_retrieval() -> None:
    agent = _make_agent()
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="unknown")
    mock_llm_cls = MagicMock(return_value=mock_llm)

    with patch("app.pipelines.query.router.LLM_REGISTRY", {"anthropic": mock_llm_cls}):
        route = await route_query("query", agent, "req-1", "tenant-1")

    assert route == "retrieval"


@pytest.mark.asyncio
async def test_route_query_emits_structured_log() -> None:
    agent = _make_agent()
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="direct")
    mock_llm_cls = MagicMock(return_value=mock_llm)

    with patch("app.pipelines.query.router.LLM_REGISTRY", {"anthropic": mock_llm_cls}), patch(
        "app.pipelines.query.router.logger"
    ) as mock_logger:
        await route_query("query", agent, "req-123", "tenant-1")

    mock_logger.info.assert_called_once()
    call = mock_logger.info.call_args
    assert call.kwargs["extra"]["operation"] == "query_route"
    assert call.kwargs["extra"]["request_id"] == "req-123"
    assert call.kwargs["extra"]["extra_data"]["route"] == "direct"
    assert call.kwargs["extra"]["extra_data"]["agent_id"] == "agent-1"
    assert call.kwargs["extra"]["extra_data"]["tenant_id"] == "tenant-1"
