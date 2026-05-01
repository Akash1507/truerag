from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import NamespaceViolationError, ProviderUnavailableError
from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.models.query import Citation, QueryResponse
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
        "app.pipelines.query.pipeline._execute_retrieval",
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
    mock_execute.assert_awaited_once_with(scrubbed_query="<SCRUBBED>", top_k=3, agent=agent, filters=None)


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
        filters: dict[str, str] | None,
    ) -> QueryResponse:
        _ = scrubbed_query
        _ = top_k
        _ = agent
        _ = filters
        call_order.append("downstream")
        return QueryResponse(answer="", confidence=0.0, citations=[], latency_ms=0)

    with patch("app.pipelines.query.pipeline.scrub_pii", side_effect=_scrub), patch(
        "app.pipelines.query.pipeline._execute_retrieval",
        side_effect=_downstream,
    ):
        await run_query_pipeline("Alice alice@example.com", 4, agent)

    assert call_order == ["scrub", "downstream"]


def _make_vector_result(document_id: str = "doc-1", chunk_index: int = 0, text: str = "relevant chunk text") -> VectorResult:
    return VectorResult(
        id=f"{document_id}_{chunk_index}",
        score=0.92,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id=document_id,
            chunk_index=chunk_index,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text=text,
    )


@pytest.mark.asyncio
async def test_pipeline_embeds_and_queries_vector_store() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_make_vector_result()])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.scrub_pii", return_value="<SCRUBBED>"),
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
    ):
        await run_query_pipeline("my query", 5, agent)

    mock_embedder.embed.assert_awaited_once_with(["<SCRUBBED>"])
    mock_vector_store.query.assert_awaited_once_with("tenant-1_agent-1", [0.1, 0.2, 0.3], 5, None)


@pytest.mark.asyncio
async def test_pipeline_maps_results_to_citations() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(
        return_value=[
            _make_vector_result(document_id="doc-1", chunk_index=0, text="chunk one"),
            _make_vector_result(document_id="doc-2", chunk_index=1, text="chunk two"),
        ]
    )
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
    ):
        response = await run_query_pipeline("my query", 5, agent)

    assert response.answer == ""
    assert response.confidence == 0.0
    assert response.citations == [
        Citation(document_name="doc-1", chunk_text="chunk one", page_reference=None),
        Citation(document_name="doc-2", chunk_text="chunk two", page_reference=None),
    ]


@pytest.mark.asyncio
async def test_pipeline_passes_filters_to_vector_store() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_make_vector_result()])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)
    filters = {"document_id": "doc-1"}

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
    ):
        await run_query_pipeline("my query", 5, agent, filters=filters)

    mock_vector_store.query.assert_awaited_once_with("tenant-1_agent-1", [0.1, 0.2, 0.3], 5, filters)


@pytest.mark.asyncio
async def test_pipeline_unregistered_embedding_provider_raises_503() -> None:
    agent = _make_agent()
    agent.embedding_provider = "unknown"

    with pytest.raises(ProviderUnavailableError):
        await run_query_pipeline("my query", 5, agent)


@pytest.mark.asyncio
async def test_pipeline_unregistered_vector_store_raises_503() -> None:
    agent = _make_agent()
    agent.vector_store = "unknown"
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    with patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}), pytest.raises(
        ProviderUnavailableError
    ):
        await run_query_pipeline("my query", 5, agent)


@pytest.mark.asyncio
async def test_pipeline_empty_embedding_result_raises_provider_unavailable() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    with patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}), pytest.raises(
        ProviderUnavailableError,
        match="returned no vectors",
    ):
        await run_query_pipeline("my query", 5, agent)


@pytest.mark.asyncio
async def test_pipeline_embedder_provider_error_propagates() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(side_effect=ProviderUnavailableError("embed failed"))
    mock_embedder_cls = MagicMock(return_value=mock_embedder)

    with patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}), pytest.raises(
        ProviderUnavailableError,
        match="embed failed",
    ):
        await run_query_pipeline("my query", 5, agent)


@pytest.mark.asyncio
async def test_pipeline_vector_store_provider_error_propagates() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(side_effect=ProviderUnavailableError("query failed"))
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        pytest.raises(ProviderUnavailableError, match="query failed"),
    ):
        await run_query_pipeline("my query", 5, agent)


@pytest.mark.asyncio
async def test_pipeline_namespace_violation_propagates() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(side_effect=NamespaceViolationError("namespace mismatch"))
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        pytest.raises(NamespaceViolationError, match="namespace mismatch"),
    ):
        await run_query_pipeline("my query", 5, agent)


@pytest.mark.asyncio
async def test_pipeline_emits_embedding_and_retrieval_logs() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(
        return_value=[
            _make_vector_result(document_id="doc-1", chunk_index=0, text="chunk one"),
            _make_vector_result(document_id="doc-2", chunk_index=1, text="chunk two"),
        ]
    )
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        patch("app.pipelines.query.pipeline.logger") as mock_logger,
    ):
        await run_query_pipeline("my query", 5, agent)

    embedding_calls = [call for call in mock_logger.info.call_args_list if call.args[0] == "embedding_complete"]
    retrieval_calls = [call for call in mock_logger.info.call_args_list if call.args[0] == "retrieval_complete"]

    assert len(embedding_calls) == 1
    assert len(retrieval_calls) == 1
    assert embedding_calls[0].kwargs["extra"]["extra_data"] == {
        "tenant_id": "tenant-1",
        "agent_id": "agent-1",
        "provider": "openai",
    }
    assert retrieval_calls[0].kwargs["extra"]["extra_data"] == {
        "tenant_id": "tenant-1",
        "agent_id": "agent-1",
        "chunk_count": 2,
        "provider": "pgvector",
    }


@pytest.mark.asyncio
async def test_pipeline_no_filters_passes_none_to_vector_store() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_make_vector_result()])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
    ):
        await run_query_pipeline("my query", 5, agent)

    mock_vector_store.query.assert_awaited_once_with("tenant-1_agent-1", [0.1, 0.2, 0.3], 5, None)
