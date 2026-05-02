from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.agent import AgentDocument
from app.pipelines.query.rewriter import REWRITE_PROMPT_TEMPLATE, rewrite_query


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
        query_rewrite=True,
        rerank_pool_size=20,
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_rewrite_query_calls_llm_and_returns_rewritten_query() -> None:
    agent = _make_agent()
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="rewritten text")
    mock_llm_cls = MagicMock(return_value=mock_llm)
    query = "What is RAG?"

    with patch("app.pipelines.query.rewriter.LLM_REGISTRY", {"anthropic": mock_llm_cls}):
        rewritten = await rewrite_query(query, agent)

    assert rewritten == "rewritten text"
    mock_llm.generate.assert_awaited_once_with(REWRITE_PROMPT_TEMPLATE.format(query=query), context=[])


@pytest.mark.asyncio
async def test_rewrite_query_on_llm_failure_returns_original_query() -> None:
    agent = _make_agent()
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(side_effect=RuntimeError("boom"))
    mock_llm_cls = MagicMock(return_value=mock_llm)

    with patch("app.pipelines.query.rewriter.LLM_REGISTRY", {"anthropic": mock_llm_cls}):
        rewritten = await rewrite_query("How to tune BM25?", agent)

    assert rewritten == "How to tune BM25?"
