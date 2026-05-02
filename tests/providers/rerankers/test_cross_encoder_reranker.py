from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.models.chunk import Chunk, ChunkMetadata
from app.providers.rerankers.cross_encoder import CrossEncoderReranker


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


def test_cross_encoder_reranker_returns_descending_order() -> None:
    chunks = [_make_chunk(0), _make_chunk(1), _make_chunk(2)]
    mocked_model = MagicMock()
    mocked_model.predict.return_value = [0.2, 0.9, 0.6]

    with patch("app.providers.rerankers.cross_encoder.SentenceTransformerCrossEncoder", return_value=mocked_model):
        reranker = CrossEncoderReranker()
        result = reranker.rerank(query="query", chunks=chunks, top_k=3)

    assert [chunk.metadata.chunk_index for chunk in result] == [1, 2, 0]


def test_cross_encoder_reranker_truncates_to_top_k() -> None:
    chunks = [_make_chunk(0), _make_chunk(1), _make_chunk(2)]
    mocked_model = MagicMock()
    mocked_model.predict.return_value = [0.2, 0.9, 0.6]

    with patch("app.providers.rerankers.cross_encoder.SentenceTransformerCrossEncoder", return_value=mocked_model):
        reranker = CrossEncoderReranker()
        result = reranker.rerank(query="query", chunks=chunks, top_k=2)

    assert [chunk.metadata.chunk_index for chunk in result] == [1, 2]


def test_cross_encoder_reranker_returns_all_sorted_when_top_k_large() -> None:
    chunks = [_make_chunk(0), _make_chunk(1)]
    mocked_model = MagicMock()
    mocked_model.predict.return_value = [0.2, 0.9]

    with patch("app.providers.rerankers.cross_encoder.SentenceTransformerCrossEncoder", return_value=mocked_model):
        reranker = CrossEncoderReranker()
        result = reranker.rerank(query="query", chunks=chunks, top_k=10)

    assert [chunk.metadata.chunk_index for chunk in result] == [1, 0]
