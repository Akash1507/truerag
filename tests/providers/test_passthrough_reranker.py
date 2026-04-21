from datetime import UTC, datetime

from app.models.chunk import Chunk, ChunkMetadata
from app.providers.rerankers.passthrough import PassthroughReranker


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


def test_passthrough_reranker_returns_unchanged() -> None:
    reranker = PassthroughReranker()
    chunks = [_make_chunk(0), _make_chunk(1), _make_chunk(2)]
    result = reranker.rerank(query="test", chunks=chunks, top_k=2)
    assert result is chunks  # pure passthrough — same list object, no copy


def test_passthrough_reranker_empty_input() -> None:
    reranker = PassthroughReranker()
    result = reranker.rerank(query="test", chunks=[], top_k=5)
    assert result == []


def test_passthrough_reranker_preserves_order() -> None:
    reranker = PassthroughReranker()
    chunks = [_make_chunk(2), _make_chunk(0), _make_chunk(1)]
    result = reranker.rerank(query="query", chunks=chunks, top_k=10)
    assert result[0].metadata.chunk_index == 2
    assert result[1].metadata.chunk_index == 0
    assert result[2].metadata.chunk_index == 1


def test_passthrough_reranker_does_not_slice_top_k() -> None:
    """top_k must be ignored — passthrough returns ALL input chunks."""
    reranker = PassthroughReranker()
    chunks = [_make_chunk(i) for i in range(5)]
    result = reranker.rerank(query="test", chunks=chunks, top_k=2)
    assert len(result) == 5  # must NOT slice to 2


def test_passthrough_reranker_is_instance_of_reranker() -> None:
    from app.interfaces.reranker import Reranker

    reranker = PassthroughReranker()
    assert isinstance(reranker, Reranker)
