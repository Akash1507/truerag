from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.chunk import Chunk, ChunkMetadata
from app.providers.rerankers.cohere import CohereReranker


def _make_chunk(index: int) -> Chunk:
    return Chunk(
        text=f"chunk {index}",
        metadata=ChunkMetadata(
            tenant_id="t1",
            agent_id="a1",
            document_id="d1",
            chunk_index=index,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
    )


def test_cohere_reranker_calls_api_with_query_documents_and_top_k() -> None:
    chunks = [_make_chunk(0), _make_chunk(1), _make_chunk(2)]
    fake_client = MagicMock()
    fake_client.rerank.return_value = SimpleNamespace(results=[SimpleNamespace(index=2), SimpleNamespace(index=0)])

    with (
        patch("app.providers.rerankers.cohere.get_secret", return_value="cohere-key"),
        patch("app.providers.rerankers.cohere.cohere.ClientV2", return_value=fake_client),
        patch("app.providers.rerankers.cohere.record_reranker_call") as mock_record_reranker_call,
    ):
        reranker = CohereReranker()
        result = reranker.rerank(query="my query", chunks=chunks, top_k=2)

    fake_client.rerank.assert_called_once_with(
        model="rerank-english-v3.0",
        query="my query",
        documents=["chunk 0", "chunk 1", "chunk 2"],
        top_n=2,
    )
    mock_record_reranker_call.assert_called_once()
    assert [chunk.metadata.chunk_index for chunk in result] == [2, 0]


def test_cohere_reranker_fetches_secret_once() -> None:
    chunks = [_make_chunk(0)]
    fake_client = MagicMock()
    fake_client.rerank.return_value = SimpleNamespace(results=[SimpleNamespace(index=0)])

    with (
        patch("app.providers.rerankers.cohere.get_secret", return_value="cohere-key") as mock_secret,
        patch("app.providers.rerankers.cohere.cohere.ClientV2", return_value=fake_client),
    ):
        reranker = CohereReranker()
        reranker.rerank(query="q1", chunks=chunks, top_k=1)
        reranker.rerank(query="q2", chunks=chunks, top_k=1)

    assert mock_secret.call_count == 1


def test_cohere_reranker_retries_transient_failures() -> None:
    chunks = [_make_chunk(0)]
    fake_client = MagicMock()
    fake_client.rerank.side_effect = [RuntimeError("temporary"), SimpleNamespace(results=[SimpleNamespace(index=0)])]

    with (
        patch("app.providers.rerankers.cohere.get_secret", return_value="cohere-key"),
        patch("app.providers.rerankers.cohere.cohere.ClientV2", return_value=fake_client),
        patch("app.providers.rerankers.cohere.asyncio.sleep", new_callable=AsyncMock),
    ):
        reranker = CohereReranker()
        result = reranker.rerank(query="q", chunks=chunks, top_k=1)

    assert [chunk.metadata.chunk_index for chunk in result] == [0]
    assert fake_client.rerank.call_count == 2
