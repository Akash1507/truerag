import pytest

from app.interfaces.chunking_strategy import ChunkingStrategy
from app.interfaces.embedding_provider import EmbeddingProvider
from app.interfaces.llm_provider import LLMProvider
from app.interfaces.reranker import Reranker
from app.interfaces.vector_store import VectorStore


def test_vector_store_is_abstract() -> None:
    with pytest.raises(TypeError):
        VectorStore()  # type: ignore[abstract]


def test_chunking_strategy_is_abstract() -> None:
    with pytest.raises(TypeError):
        ChunkingStrategy()  # type: ignore[abstract]


def test_reranker_is_abstract() -> None:
    with pytest.raises(TypeError):
        Reranker()  # type: ignore[abstract]


def test_embedding_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        EmbeddingProvider()  # type: ignore[abstract]


def test_llm_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_vector_store_has_abstract_methods() -> None:
    abstract = getattr(VectorStore, "__abstractmethods__", frozenset())
    assert "upsert" in abstract
    assert "query" in abstract
    assert "delete_namespace" in abstract
    assert "health" in abstract


def test_chunking_strategy_has_abstract_methods() -> None:
    abstract = getattr(ChunkingStrategy, "__abstractmethods__", frozenset())
    assert "chunk" in abstract


def test_reranker_has_abstract_methods() -> None:
    abstract = getattr(Reranker, "__abstractmethods__", frozenset())
    assert "rerank" in abstract


def test_embedding_provider_has_abstract_methods() -> None:
    abstract = getattr(EmbeddingProvider, "__abstractmethods__", frozenset())
    assert "embed" in abstract


def test_llm_provider_has_abstract_methods() -> None:
    abstract = getattr(LLMProvider, "__abstractmethods__", frozenset())
    assert "generate" in abstract
