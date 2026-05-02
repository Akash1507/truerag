from datetime import datetime, timezone

from app.models.chunk import ChunkMetadata
from app.providers.chunking.document_aware import DocumentAwareChunker


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


def test_markdown_headings_split_sections() -> None:
    text = "# Title\nalpha\n## Subtitle\nbeta"
    chunker = DocumentAwareChunker(max_chunk_tokens=512)
    chunks = chunker.chunk(text, _make_metadata())
    assert len(chunks) >= 2
    assert chunks[0].metadata.chunking_strategy == "document_aware"


def test_table_block_not_split_mid_row() -> None:
    text = "# Table\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## Next\ncontent"
    chunker = DocumentAwareChunker(max_chunk_tokens=512)
    chunks = chunker.chunk(text, _make_metadata())
    table_chunks = [c for c in chunks if "| a | b |" in c.text or "| 1 | 2 |" in c.text]
    assert len(table_chunks) == 1


def test_oversized_section_subchunked() -> None:
    text = "# Big\n" + ("word " * 2000)
    chunker = DocumentAwareChunker(max_chunk_tokens=64)
    chunks = chunker.chunk(text, _make_metadata())
    assert len(chunks) > 1


def test_empty_text_returns_empty_list() -> None:
    chunker = DocumentAwareChunker()
    assert chunker.chunk("", _make_metadata()) == []
