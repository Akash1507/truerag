import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import _execute_retrieval


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
        multi_query_enabled=True,
        multi_query_count=3,
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
    )


@pytest.mark.asyncio
async def test_multi_query_generates_variants_and_merges_with_rrf() -> None:
    agent = _agent()
    variants = ["v1", "v2", "v3"]
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value=json.dumps(variants))
    provider_cls = MagicMock(return_value=provider)

    mock_embedder = AsyncMock()
    vectors_by_text = {"v1": [1.0, 0.0], "v2": [0.0, 1.0], "v3": [1.0, 1.0]}
    mock_embedder.embed = AsyncMock(side_effect=lambda texts: [vectors_by_text[texts[0]]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(
        side_effect=[
            [_result("a", 0.6), _result("shared", 0.9)],
            [_result("shared", 0.7), _result("b", 0.8)],
            [_result("c", 0.5), _result("shared", 0.4)],
        ]
    )
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.LLM_REGISTRY", {"anthropic": provider_cls}),
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
    ):
        results = await _execute_retrieval("query", 2, agent, None)

    assert mock_embedder.embed.await_count == 3
    assert mock_vector_store.query.await_count == 3
    assert len(results) == 2
    assert results[0].id == "shared"


@pytest.mark.asyncio
async def test_multi_query_json_parse_failure_falls_back_to_single_query() -> None:
    agent = _agent()
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value="not-json")
    provider_cls = MagicMock(return_value=provider)

    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[1.0, 0.0]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_result("a", 0.9)])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.LLM_REGISTRY", {"anthropic": provider_cls}),
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
    ):
        await _execute_retrieval("query", 2, agent, None)

    mock_embedder.embed.assert_awaited_once_with(["query"])
    mock_vector_store.query.assert_awaited_once()


@pytest.mark.asyncio
async def test_multi_query_llm_failure_falls_back_to_standard_dense() -> None:
    agent = _agent()
    provider = AsyncMock()
    provider.generate = AsyncMock(side_effect=RuntimeError("llm down"))
    provider_cls = MagicMock(return_value=provider)

    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[2.0, 2.0]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_result("fallback", 0.8)])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.LLM_REGISTRY", {"anthropic": provider_cls}),
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
    ):
        results = await _execute_retrieval("query", 2, agent, None)

    assert [result.id for result in results] == ["fallback"]
    mock_embedder.embed.assert_awaited_once_with(["query"])
    mock_vector_store.query.assert_awaited_once()
