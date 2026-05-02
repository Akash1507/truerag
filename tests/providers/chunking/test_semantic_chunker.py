from datetime import datetime, timezone
from typing import Any

from app.models.chunk import ChunkMetadata
from app.providers.chunking.semantic import SemanticChunker


class _FakeSentence:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeDoc:
    def __init__(self, sentences: list[str]) -> None:
        self.sents = [_FakeSentence(s) for s in sentences]


class _FakeNLP:
    def __call__(self, text: str) -> _FakeDoc:
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        return _FakeDoc([f"{s}." for s in sentences])


class _FakeEncoder:
    def encode(self, sentences: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for sentence in sentences:
            if "split" in sentence.lower():
                vectors.append([1.0, 0.0])
            elif "different" in sentence.lower():
                vectors.append([0.0, 1.0])
            else:
                vectors.append([1.0, 0.0])
        return vectors


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


def _chunker(monkeypatch: Any) -> SemanticChunker:
    monkeypatch.setattr(SemanticChunker, "_load_spacy_pipeline", lambda self: _FakeNLP())
    monkeypatch.setattr(SemanticChunker, "_load_sentence_encoder", lambda self: _FakeEncoder())
    return SemanticChunker(similarity_threshold=0.75, max_chunk_tokens=512)


def test_single_sentence_returns_one_chunk(monkeypatch: Any) -> None:
    chunker = _chunker(monkeypatch)
    chunks = chunker.chunk("Only one sentence.", _make_metadata())
    assert len(chunks) == 1
    assert chunks[0].metadata.chunking_strategy == "semantic"


def test_multi_sentence_low_similarity_splits_chunks(monkeypatch: Any) -> None:
    chunker = _chunker(monkeypatch)
    text = "Keep together sentence. Split boundary sentence. Different topic sentence."
    chunks = chunker.chunk(text, _make_metadata())
    assert len(chunks) >= 2


def test_metadata_strategy_and_index_sequential(monkeypatch: Any) -> None:
    chunker = _chunker(monkeypatch)
    text = "Keep sentence. Split sentence. Different sentence."
    chunks = chunker.chunk(text, _make_metadata())
    for i, chunk in enumerate(chunks):
        assert chunk.metadata.chunk_index == i
        assert chunk.metadata.chunking_strategy == "semantic"
        assert chunk.metadata.tenant_id == "tenant-1"


def test_empty_text_returns_empty_list(monkeypatch: Any) -> None:
    chunker = _chunker(monkeypatch)
    assert chunker.chunk("", _make_metadata()) == []
