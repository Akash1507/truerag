from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.chunk import Chunk, ChunkMetadata
from app.providers.rerankers.cohere import CohereReranker
from app.providers.rerankers.cross_encoder import CrossEncoderReranker
from app.providers.rerankers.passthrough import PassthroughReranker


def _make_chunks(size: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i in range(size):
        chunks.append(
            Chunk(
                text=f"chunk {i}",
                metadata=ChunkMetadata(
                    tenant_id="tenant-1",
                    agent_id="agent-1",
                    document_id="doc-1",
                    chunk_index=i,
                    chunking_strategy="fixed_size",
                    timestamp=datetime.now(UTC),
                    version=1,
                ),
            )
        )
    return chunks


def _build_reranker(name: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    if name == "none":
        return PassthroughReranker()

    if name == "cross_encoder":
        class _FakeCrossEncoder:
            def __init__(self, _: str) -> None:
                pass

            def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
                return [float(len(pairs) - i) for i in range(len(pairs))]

        monkeypatch.setattr(
            "app.providers.rerankers.cross_encoder.SentenceTransformerCrossEncoder",
            _FakeCrossEncoder,
        )
        return CrossEncoderReranker()

    if name == "cohere":
        class _FakeClient:
            def __init__(self, *, api_key: str) -> None:
                del api_key

            def rerank(
                self, *, model: str, query: str, documents: list[str], top_n: int
            ) -> SimpleNamespace:
                del model, query
                return SimpleNamespace(
                    results=[SimpleNamespace(index=i) for i in range(min(top_n, len(documents)))]
                )

        monkeypatch.setattr("app.providers.rerankers.cohere.cohere.ClientV2", _FakeClient)
        monkeypatch.setattr(CohereReranker, "_get_api_key", lambda self: "test-key")
        return CohereReranker()

    raise AssertionError(f"unexpected reranker: {name}")


@pytest.mark.parametrize("reranker_name", ["none", "cross_encoder", "cohere"])
def test_reranker_contract_output_type_and_no_input_mutation(
    reranker_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    reranker = _build_reranker(reranker_name, monkeypatch)
    chunks = _make_chunks(5)
    original = list(chunks)

    result = reranker.rerank(query="q", chunks=chunks, top_k=3)

    assert isinstance(result, list)
    assert chunks == original


@pytest.mark.parametrize("reranker_name", ["cross_encoder", "cohere"])
def test_reranker_contract_respects_top_k_when_enough_chunks(
    reranker_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    reranker = _build_reranker(reranker_name, monkeypatch)
    chunks = _make_chunks(5)

    result = reranker.rerank(query="q", chunks=chunks, top_k=3)

    assert len(result) == 3


@pytest.mark.parametrize("reranker_name", ["none", "cross_encoder", "cohere"])
def test_reranker_contract_returns_all_when_top_k_exceeds_input(
    reranker_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    reranker = _build_reranker(reranker_name, monkeypatch)
    chunks = _make_chunks(2)

    result = reranker.rerank(query="q", chunks=chunks, top_k=5)

    assert len(result) == 2
