from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import run_query_pipeline


def _make_agent(*, hallucination_check_enabled: bool) -> AgentDocument:
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
        query_rewrite=False,
        hallucination_check_enabled=hallucination_check_enabled,
        rerank_pool_size=20,
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        embedding_provider_mismatch=False,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_result() -> VectorResult:
    return VectorResult(
        id="doc-1_0",
        score=0.9,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id="doc-1",
            chunk_index=0,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text="chunk one",
    )


@pytest.mark.asyncio
async def test_pipeline_sets_hallucination_risk_when_enabled() -> None:
    agent = _make_agent(hallucination_check_enabled=True)

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch("app.pipelines.query.pipeline._execute_retrieval", AsyncMock(return_value=[_make_result()])),
        patch("app.pipelines.query.pipeline._execute_rerank", return_value=[_make_result()]),
        patch("app.pipelines.query.pipeline._execute_generation", AsyncMock(return_value="answer")),
        patch("app.pipelines.query.pipeline.check_hallucination", AsyncMock(return_value="medium")) as check_mock,
        patch("app.pipelines.query.pipeline.log_stage_latency") as stage_latency_mock,
    ):
        response = await run_query_pipeline("raw", 5, agent)

    assert response.hallucination_risk == "medium"
    check_mock.assert_awaited_once()
    stage_names = [call.args[1] for call in stage_latency_mock.call_args_list]
    assert "hallucination_check" in stage_names


@pytest.mark.asyncio
async def test_pipeline_sets_hallucination_risk_none_when_disabled() -> None:
    agent = _make_agent(hallucination_check_enabled=False)

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch("app.pipelines.query.pipeline._execute_retrieval", AsyncMock(return_value=[_make_result()])),
        patch("app.pipelines.query.pipeline._execute_rerank", return_value=[_make_result()]),
        patch("app.pipelines.query.pipeline._execute_generation", AsyncMock(return_value="answer")),
        patch("app.pipelines.query.pipeline.check_hallucination", AsyncMock(return_value="high")) as check_mock,
    ):
        response = await run_query_pipeline("raw", 5, agent)

    assert response.hallucination_risk is None
    check_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_direct_route_sets_hallucination_risk_none() -> None:
    agent = _make_agent(hallucination_check_enabled=True)

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="direct")),
        patch("app.pipelines.query.pipeline._execute_direct_generation", AsyncMock(return_value="direct answer")),
        patch("app.pipelines.query.pipeline.check_hallucination", AsyncMock(return_value="low")) as check_mock,
    ):
        response = await run_query_pipeline("raw", 5, agent)

    assert response.hallucination_risk is None
    check_mock.assert_not_awaited()
