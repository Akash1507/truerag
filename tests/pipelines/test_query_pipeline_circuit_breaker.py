from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import ProviderUnavailableError, ServiceUnavailableError
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import QueryPipelineCircuitBreakers, run_query_pipeline
from app.utils.circuit_breaker import CircuitBreaker


def _make_agent() -> SimpleNamespace:
    return SimpleNamespace(
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
        embedding_provider_mismatch=False,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        hallucination_check_enabled=False,
        context_window_tokens=8192,
        hyde_enabled=False,
        multi_query_enabled=False,
        multi_query_count=3,
        mmr_enabled=False,
        mmr_lambda=0.5,
    )


def _result() -> VectorResult:
    return VectorResult(
        id="chunk-1",
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
        text="context chunk",
    )


@pytest.mark.asyncio
async def test_embedder_failures_open_circuit_and_raise_503() -> None:
    agent = _make_agent()
    breakers = QueryPipelineCircuitBreakers()
    breakers._cb_embed = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=60)

    embedder = AsyncMock()
    embedder.embed = AsyncMock(side_effect=RuntimeError("embed down"))
    embedder_cls = MagicMock(return_value=embedder)
    vector_store = AsyncMock()
    vector_store.query = AsyncMock(return_value=[_result()])
    vector_store_cls = MagicMock(return_value=vector_store)

    with (
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": vector_store_cls}),
    ):
        with pytest.raises(ProviderUnavailableError):
            await run_query_pipeline("q", 2, agent, circuit_breakers=breakers)
        with pytest.raises(ProviderUnavailableError):
            await run_query_pipeline("q", 2, agent, circuit_breakers=breakers)
        with pytest.raises(ServiceUnavailableError):
            await run_query_pipeline("q", 2, agent, circuit_breakers=breakers)


@pytest.mark.asyncio
async def test_pipeline_recovers_after_timeout_when_embedder_succeeds() -> None:
    agent = _make_agent()
    breakers = QueryPipelineCircuitBreakers()
    breakers._cb_embed = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0)

    embedder = AsyncMock()
    embedder.embed = AsyncMock(side_effect=[RuntimeError("embed down"), [[0.1, 0.2]]])
    embedder_cls = MagicMock(return_value=embedder)
    vector_store = AsyncMock()
    vector_store.query = AsyncMock(return_value=[_result()])
    vector_store_cls = MagicMock(return_value=vector_store)

    with (
        patch("app.pipelines.query.pipeline.route_query", AsyncMock(return_value="retrieval")),
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": vector_store_cls}),
        patch("app.pipelines.query.pipeline.generate_answer", AsyncMock(return_value="ok")),
    ):
        with pytest.raises(ProviderUnavailableError):
            await run_query_pipeline("q", 2, agent, circuit_breakers=breakers)

        response = await run_query_pipeline("q", 2, agent, circuit_breakers=breakers)

    assert response.answer == "ok"
