from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import _execute_retrieval, run_query_pipeline


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
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _result(result_id: str, score: float = 0.9) -> VectorResult:
    return VectorResult(
        id=result_id,
        score=score,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id="doc-1",
            chunk_index=0,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text=f"text-{result_id}",
        embedding=[1.0, 0.0],
    )


@pytest.mark.asyncio
async def test_hyde_takes_precedence_when_hyde_and_multi_query_enabled() -> None:
    agent = _agent()
    agent.hyde_enabled = True
    agent.multi_query_enabled = True

    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[1.0, 0.0]])
    mock_vector_store = AsyncMock()

    with (
        patch(
            "app.pipelines.query.pipeline.EMBEDDING_REGISTRY",
            {"openai": lambda: mock_embedder},
        ),
        patch(
            "app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY",
            {"pgvector": lambda: mock_vector_store},
        ),
        patch(
            "app.pipelines.query.pipeline._hyde_retrieve",
            AsyncMock(return_value=[_result("hyde")]),
        ) as hyde_mock,
        patch(
            "app.pipelines.query.pipeline._multi_query_retrieve",
            AsyncMock(return_value=[_result("multi")]),
        ) as multi_mock,
        patch("app.pipelines.query.pipeline.logger.warning") as warning_mock,
    ):
        results = await _execute_retrieval("query", 3, agent, None)

    assert [item.id for item in results] == ["hyde"]
    hyde_mock.assert_awaited_once()
    multi_mock.assert_not_awaited()
    warning_mock.assert_any_call(
        "hyde_and_multi_query_both_enabled_hyde_precedence",
        extra={
            "operation": "retrieval",
            "extra_data": {"tenant_id": "tenant-1", "agent_id": "agent-1"},
        },
    )


@pytest.mark.asyncio
async def test_mmr_applies_after_reranking() -> None:
    agent = _agent()
    agent.mmr_enabled = True

    reranked = [_result("reranked-1"), _result("reranked-2")]
    mmr_selected = [_result("mmr-1")]

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch(
            "app.pipelines.query.pipeline._execute_retrieval",
            AsyncMock(return_value=[_result("retrieved-1"), _result("retrieved-2")]),
        ),
        patch(
            "app.pipelines.query.pipeline._execute_rerank",
            AsyncMock(return_value=reranked),
        ),
        patch(
            "app.pipelines.query.pipeline._apply_mmr_if_enabled",
            side_effect=lambda **kwargs: mmr_selected,
        ) as mmr_mock,
        patch("app.pipelines.query.pipeline._execute_generation", AsyncMock(return_value="answer")) as gen_mock,
    ):
        await run_query_pipeline("query", 2, agent)

    mmr_kwargs = mmr_mock.call_args.kwargs
    assert mmr_kwargs["results"] == reranked
    assert mmr_kwargs["top_k"] == 2
    assert mmr_kwargs["agent"] is agent
    assert gen_mock.await_args.kwargs["results"] == mmr_selected
