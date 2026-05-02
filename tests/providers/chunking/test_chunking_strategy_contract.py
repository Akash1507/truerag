from datetime import UTC, datetime
from typing import Any

import pytest

from app.models.chunk import ChunkMetadata
from app.providers.chunking.document_aware import DocumentAwareChunker
from app.providers.chunking.fixed_size import FixedSizeChunker
from app.providers.chunking.hierarchical import HierarchicalChunker
from app.providers.chunking.keyword import KeywordChunker
from app.providers.chunking.semantic import SemanticChunker


def _metadata(strategy: str) -> ChunkMetadata:
    return ChunkMetadata(
        tenant_id="tenant-1",
        agent_id="agent-1",
        document_id="doc-1",
        chunk_index=0,
        chunking_strategy=strategy,
        timestamp=datetime.now(UTC),
        version=1,
    )


class _FakeDoc:
    def __init__(self, text: str) -> None:
        self.sents = [type("Sent", (), {"text": text})()]


class _FakeNLP:
    def __call__(self, text: str) -> _FakeDoc:
        return _FakeDoc(text.strip())


class _FakeEncoder:
    def encode(self, sentences: list[str]) -> list[list[float]]:
        return [[float(i + 1)] * 3 for i, _ in enumerate(sentences)]


def _make_chunker(strategy: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    if strategy == "fixed_size":
        return FixedSizeChunker(chunk_size=32, chunk_overlap=4)
    if strategy == "hierarchical":
        return HierarchicalChunker(parent_chunk_tokens=64, child_chunk_tokens=16, child_overlap=4)
    if strategy == "document_aware":
        return DocumentAwareChunker(max_chunk_tokens=32)
    if strategy == "keyword":
        return KeywordChunker(max_chunk_tokens=32)
    if strategy == "semantic":
        monkeypatch.setattr(SemanticChunker, "_load_spacy_pipeline", lambda self: _FakeNLP())
        monkeypatch.setattr(SemanticChunker, "_load_sentence_encoder", lambda self: _FakeEncoder())
        return SemanticChunker(max_chunk_tokens=32)
    raise AssertionError(f"unexpected strategy: {strategy}")


@pytest.mark.parametrize(
    "strategy",
    ["fixed_size", "semantic", "hierarchical", "document_aware", "keyword"],
)
def test_chunking_contract_empty_text_returns_empty(
    strategy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunker = _make_chunker(strategy, monkeypatch)
    assert chunker.chunk("", _metadata(strategy)) == []


@pytest.mark.parametrize(
    "strategy",
    ["fixed_size", "semantic", "hierarchical", "document_aware", "keyword"],
)
def test_chunking_contract_metadata_and_shape(
    strategy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunker = _make_chunker(strategy, monkeypatch)
    chunks = chunker.chunk("Paragraph one.\n\nParagraph two.", _metadata(strategy))

    assert isinstance(chunks, list)
    assert len(chunks) >= 1
    assert [chunk.metadata.chunk_index for chunk in chunks] == list(range(len(chunks)))

    for chunk in chunks:
        assert chunk.text.strip() != ""
        assert chunk.metadata.tenant_id == "tenant-1"
        assert chunk.metadata.agent_id == "agent-1"
        assert chunk.metadata.document_id == "doc-1"
        assert chunk.metadata.chunking_strategy == strategy
