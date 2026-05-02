from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import ProviderUnavailableError
from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import _execute_retrieval, run_query_pipeline


def _make_agent(retrieval_mode: str = "dense") -> AgentDocument:
    return AgentDocument(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode=retrieval_mode,
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


def _result(result_id: str, score: float = 0.5) -> VectorResult:
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
    )


@pytest.mark.asyncio
async def test_retrieval_mode_sparse_uses_sparse_retriever_only() -> None:
    agent = _make_agent("sparse")
    mock_vector_store = AsyncMock()
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)
    sparse_mock = AsyncMock(return_value=[_result("sparse")])

    with (
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        patch("app.pipelines.query.pipeline.retrieve_sparse", sparse_mock),
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {}),
    ):
        results = await _execute_retrieval("q", 3, agent, None)

    assert [result.id for result in results] == ["sparse"]
    sparse_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieval_mode_hybrid_calls_dense_and_sparse_and_applies_rrf() -> None:
    agent = _make_agent("hybrid")
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_result("dense-a"), _result("shared")])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)
    sparse_mock = AsyncMock(return_value=[_result("shared"), _result("sparse-b")])

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        patch("app.pipelines.query.pipeline.retrieve_sparse", sparse_mock),
    ):
        results = await _execute_retrieval("q", 3, agent, None)

    assert len(results) == 3
    assert mock_vector_store.query.await_count == 1
    sparse_mock.assert_awaited_once()
    mock_embedder.embed.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieval_mode_dense_unchanged() -> None:
    agent = _make_agent("dense")
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    dense_results = [_result("dense-a"), _result("dense-b")]
    mock_vector_store.query = AsyncMock(return_value=dense_results)
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
    ):
        results = await _execute_retrieval("q", 2, agent, None)

    assert results == dense_results


@pytest.mark.asyncio
async def test_hybrid_failure_raises_provider_unavailable_no_partial_results() -> None:
    agent = _make_agent("hybrid")
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_result("dense-a")])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        patch("app.pipelines.query.pipeline.retrieve_sparse", AsyncMock(side_effect=RuntimeError("boom"))),
        pytest.raises(ProviderUnavailableError, match="Hybrid retrieval failed"),
    ):
        await _execute_retrieval("q", 2, agent, None)


@pytest.mark.asyncio
async def test_run_query_pipeline_direct_route_skips_retrieval_and_returns_empty_citations() -> None:
    agent = _make_agent("dense")

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="direct")),
        patch("app.pipelines.query.pipeline._execute_direct_generation", AsyncMock(return_value="direct answer")),
        patch("app.pipelines.query.pipeline._execute_retrieval", AsyncMock()) as retrieval_mock,
    ):
        response = await run_query_pipeline(query="raw", top_k=5, agent=agent)

    retrieval_mock.assert_not_awaited()
    assert response.answer == "direct answer"
    assert response.citations == []
    assert response.confidence == 0.0


@pytest.mark.asyncio
async def test_run_query_pipeline_retrieval_route_with_query_rewrite_calls_rewriter_before_retrieval() -> None:
    agent = _make_agent("dense")
    agent.query_rewrite = True

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch("app.pipelines.query.pipeline.rewrite_query", AsyncMock(return_value="rewritten query")) as rewrite_mock,
        patch(
            "app.pipelines.query.pipeline._execute_retrieval",
            AsyncMock(return_value=[_result("a", 0.9)]),
        ) as retrieval_mock,
        patch("app.pipelines.query.pipeline._execute_rerank", return_value=[_result("a", 0.9)]),
        patch("app.pipelines.query.pipeline._execute_generation", AsyncMock(return_value="answer")),
    ):
        response = await run_query_pipeline(query="raw", top_k=5, agent=agent)

    rewrite_mock.assert_awaited_once_with("clean query", agent)
    retrieval_mock.assert_awaited_once_with(
        scrubbed_query="rewritten query",
        top_k=5,
        agent=agent,
        filters=None,
    )
    assert response.answer == "answer"


@pytest.mark.asyncio
async def test_run_query_pipeline_retrieval_route_without_query_rewrite_does_not_call_rewriter() -> None:
    agent = _make_agent("dense")
    agent.query_rewrite = False

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch("app.pipelines.query.pipeline.rewrite_query", AsyncMock(return_value="rewritten query")) as rewrite_mock,
        patch(
            "app.pipelines.query.pipeline._execute_retrieval",
            AsyncMock(return_value=[_result("a", 0.9)]),
        ) as retrieval_mock,
        patch("app.pipelines.query.pipeline._execute_rerank", return_value=[_result("a", 0.9)]),
        patch("app.pipelines.query.pipeline._execute_generation", AsyncMock(return_value="answer")),
    ):
        await run_query_pipeline(query="raw", top_k=5, agent=agent)

    rewrite_mock.assert_not_awaited()
    retrieval_mock.assert_awaited_once_with(
        scrubbed_query="clean query",
        top_k=5,
        agent=agent,
        filters=None,
    )


@pytest.mark.asyncio
async def test_run_query_pipeline_rewriter_fallback_uses_original_query_for_retrieval() -> None:
    agent = _make_agent("dense")
    agent.query_rewrite = True

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="clean query"),
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch(
            "app.pipelines.query.pipeline.rewrite_query",
            AsyncMock(return_value="clean query"),
        ),
        patch(
            "app.pipelines.query.pipeline._execute_retrieval",
            AsyncMock(return_value=[_result("a", 0.9)]),
        ) as retrieval_mock,
        patch("app.pipelines.query.pipeline._execute_rerank", return_value=[_result("a", 0.9)]),
        patch("app.pipelines.query.pipeline._execute_generation", AsyncMock(return_value="answer")),
    ):
        response = await run_query_pipeline(query="raw", top_k=5, agent=agent)

    retrieval_mock.assert_awaited_once_with(
        scrubbed_query="clean query",
        top_k=5,
        agent=agent,
        filters=None,
    )
    assert response.answer == "answer"
