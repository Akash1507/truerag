from datetime import datetime, timezone

from app.models.chunk import ChunkMetadata
from app.providers.chunking.hierarchical import HierarchicalChunker


def _make_metadata() -> ChunkMetadata:
    return ChunkMetadata(
        tenant_id="tenant-1",
        agent_id="agent-1",
        document_id="doc-1",
        chunk_index=0,
        chunking_strategy="fixed_size",
        timestamp=datetime(2026, 5, 2, tzinfo=timezone.utc),
        version=1,
    )


def test_child_chunks_include_parent_text() -> None:
    chunker = HierarchicalChunker(parent_chunk_tokens=30, child_chunk_tokens=10, child_overlap=2)
    chunks = chunker.chunk("word " * 100, _make_metadata())
    assert chunks
    for chunk in chunks:
        assert chunk.metadata.parent_text
        assert chunk.metadata.chunking_strategy == "hierarchical"


def test_chunk_index_is_globally_sequential() -> None:
    chunker = HierarchicalChunker(parent_chunk_tokens=20, child_chunk_tokens=8, child_overlap=2)
    chunks = chunker.chunk("word " * 120, _make_metadata())
    for i, chunk in enumerate(chunks):
        assert chunk.metadata.chunk_index == i


def test_empty_text_returns_empty_list() -> None:
    chunker = HierarchicalChunker()
    assert chunker.chunk("", _make_metadata()) == []


def test_short_text_single_parent_children_within_parent() -> None:
    chunker = HierarchicalChunker(parent_chunk_tokens=1000, child_chunk_tokens=20, child_overlap=5)
    chunks = chunker.chunk("word " * 40, _make_metadata())
    assert len(chunks) >= 1
    parent_texts = {chunk.metadata.parent_text for chunk in chunks}
    assert len(parent_texts) == 1
