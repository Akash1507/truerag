from datetime import datetime, timezone

import pytest

from app.models.chunk import ChunkMetadata
from app.providers.chunking.fixed_size import FixedSizeChunker


def _make_metadata() -> ChunkMetadata:
    return ChunkMetadata(
        tenant_id="tenant-1",
        agent_id="agent-1",
        document_id="doc-1",
        chunk_index=0,
        chunking_strategy="fixed_size",
        timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
        version=1,
    )


def test_chunk_splits_into_correct_count() -> None:
    import math
    import tiktoken

    text = "word " * 50
    enc = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(enc.encode(text))
    chunk_size = 10
    overlap = 2
    stride = chunk_size - overlap
    
    expected_chunks = math.ceil((num_tokens - overlap) / stride) if num_tokens > overlap else 1
    
    chunker = FixedSizeChunker(chunk_size=chunk_size, chunk_overlap=overlap)
    chunks = chunker.chunk(text, _make_metadata())
    assert len(chunks) == expected_chunks


def test_chunk_metadata_carried_through() -> None:
    text = "word " * 100
    chunker = FixedSizeChunker(chunk_size=20, chunk_overlap=5)
    meta = _make_metadata()
    chunks = chunker.chunk(text, meta)
    for chunk in chunks:
        assert chunk.metadata.tenant_id == "tenant-1"
        assert chunk.metadata.agent_id == "agent-1"
        assert chunk.metadata.document_id == "doc-1"
        assert chunk.metadata.chunking_strategy == "fixed_size"
        assert chunk.metadata.version == 1


def test_chunk_index_sequential() -> None:
    text = "word " * 100
    chunker = FixedSizeChunker(chunk_size=20, chunk_overlap=5)
    chunks = chunker.chunk(text, _make_metadata())
    for i, chunk in enumerate(chunks):
        assert chunk.metadata.chunk_index == i


def test_no_chunk_exceeds_token_size() -> None:
    import tiktoken

    text = "word " * 200
    chunk_size = 30
    chunker = FixedSizeChunker(chunk_size=chunk_size, chunk_overlap=5)
    chunks = chunker.chunk(text, _make_metadata())
    enc = tiktoken.get_encoding("cl100k_base")
    for chunk in chunks:
        token_count = len(enc.encode(chunk.text))
        assert token_count <= chunk_size


def test_empty_text_returns_empty_list() -> None:
    chunker = FixedSizeChunker(chunk_size=512, chunk_overlap=50)
    result = chunker.chunk("", _make_metadata())
    assert result == []


def test_overlap_guard_raises_value_error() -> None:
    with pytest.raises(ValueError):
        FixedSizeChunker(chunk_size=50, chunk_overlap=50)

    with pytest.raises(ValueError):
        FixedSizeChunker(chunk_size=50, chunk_overlap=100)


def test_single_chunk_when_text_fits() -> None:
    text = "short text"
    chunker = FixedSizeChunker(chunk_size=512, chunk_overlap=50)
    chunks = chunker.chunk(text, _make_metadata())
    assert len(chunks) == 1
    assert chunks[0].metadata.chunk_index == 0
