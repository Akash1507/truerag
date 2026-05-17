from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import _execute_retrieval
from app.utils.cost_tracker import get_cost_accumulator, init_cost_tracking, record_llm_usage


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
        hyde_enabled=True,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _result(result_id: str = "chunk-1") -> VectorResult:
    return VectorResult(
        id=result_id,
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
        text="chunk text",
    )


@pytest.mark.asyncio
async def test_hyde_uses_hypothetical_embedding_for_vector_query() -> None:
    agent = _agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(
        side_effect=lambda texts: [[9.0, 9.0]] if texts == ["hypothetical"] else [[1.0, 1.0]]
    )
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_result()])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    provider = AsyncMock()
    provider.generate = AsyncMock(return_value="hypothetical")
    provider_cls = MagicMock(return_value=provider)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        patch("app.pipelines.query.pipeline.LLM_REGISTRY", {"anthropic": provider_cls}),
    ):
        await _execute_retrieval("original query", 3, agent, None)

    provider.generate.assert_awaited_once()
    query_vector = mock_vector_store.query.await_args.args[1]
    assert query_vector == [9.0, 9.0]


@pytest.mark.asyncio
async def test_hyde_failure_falls_back_to_standard_dense_retrieval() -> None:
    agent = _agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[1.0, 1.0]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_result()])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=RuntimeError("llm down"))
    provider_cls = MagicMock(return_value=provider)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        patch("app.pipelines.query.pipeline.LLM_REGISTRY", {"anthropic": provider_cls}),
    ):
        results = await _execute_retrieval("original query", 3, agent, None)

    assert results
    query_vector = mock_vector_store.query.await_args.args[1]
    assert query_vector == [1.0, 1.0]


@pytest.mark.asyncio
async def test_hyde_records_hyde_token_usage_separately() -> None:
    init_cost_tracking()
    agent = _agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[3.0, 3.0]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_result()])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    provider = AsyncMock()

    async def _generate(_prompt: str, context: list[object]) -> str:
        _ = context
        record_llm_usage(11, 7)
        return "hypothetical"

    provider.generate = AsyncMock(side_effect=_generate)
    provider_cls = MagicMock(return_value=provider)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        patch("app.pipelines.query.pipeline.LLM_REGISTRY", {"anthropic": provider_cls}),
    ):
        await _execute_retrieval("original query", 3, agent, None)

    accumulator = get_cost_accumulator()
    assert accumulator is not None
    assert accumulator.hyde_prompt_tokens == 11
    assert accumulator.hyde_completion_tokens == 7
