from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.agent import AgentDocument
from app.models.query import QueryResponse
from app.pipelines.query.pipeline import run_query_pipeline


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
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_pipeline_uses_scrubbed_query_for_downstream() -> None:
    agent = _make_agent()
    with patch(
        "app.pipelines.query.pipeline.scrub_pii",
        return_value="<SCRUBBED>",
    ) as mock_scrub, patch(
        "app.pipelines.query.pipeline._execute_stub",
        AsyncMock(
            return_value=QueryResponse(
                answer="",
                confidence=0.0,
                citations=[],
                latency_ms=0,
            )
        ),
    ) as mock_execute:
        await run_query_pipeline("Call me at 555-123-4567", 3, agent)

    mock_scrub.assert_called_once_with("Call me at 555-123-4567")
    mock_execute.assert_awaited_once_with(scrubbed_query="<SCRUBBED>", top_k=3, agent=agent)


@pytest.mark.asyncio
async def test_pipeline_calls_scrub_once_before_downstream() -> None:
    agent = _make_agent()
    call_order: list[str] = []

    def _scrub(text: str) -> str:
        call_order.append("scrub")
        return "<SCRUBBED>"

    async def _downstream(
        *,
        scrubbed_query: str,
        top_k: int,
        agent: AgentDocument,
    ) -> QueryResponse:
        _ = scrubbed_query
        _ = top_k
        _ = agent
        call_order.append("downstream")
        return QueryResponse(answer="", confidence=0.0, citations=[], latency_ms=0)

    with patch("app.pipelines.query.pipeline.scrub_pii", side_effect=_scrub), patch(
        "app.pipelines.query.pipeline._execute_stub",
        side_effect=_downstream,
    ):
        await run_query_pipeline("Alice alice@example.com", 4, agent)

    assert call_order == ["scrub", "downstream"]
