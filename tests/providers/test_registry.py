from app.providers.chunking.fixed_size import FixedSizeChunker
from app.providers.registry import (
    CHUNKING_REGISTRY,
    EMBEDDING_REGISTRY,
    LLM_REGISTRY,
    RERANKER_REGISTRY,
    VECTOR_STORE_REGISTRY,
)
from app.providers.rerankers.passthrough import PassthroughReranker
from app.providers.vector_stores.pgvector import PgVectorStore


def test_all_five_registries_importable() -> None:
    assert isinstance(VECTOR_STORE_REGISTRY, dict)
    assert isinstance(CHUNKING_REGISTRY, dict)
    assert isinstance(RERANKER_REGISTRY, dict)
    assert isinstance(EMBEDDING_REGISTRY, dict)
    assert isinstance(LLM_REGISTRY, dict)


def test_reranker_registry_has_none_key() -> None:
    assert "none" in RERANKER_REGISTRY
    assert RERANKER_REGISTRY["none"] is PassthroughReranker


def test_none_key_returns_passthrough_instance() -> None:
    reranker = RERANKER_REGISTRY["none"]()
    assert isinstance(reranker, PassthroughReranker)


def test_registry_entries_for_current_epic() -> None:
    """Current stories register pgvector and openai providers."""
    assert VECTOR_STORE_REGISTRY == {"pgvector": PgVectorStore}
    assert "openai" in EMBEDDING_REGISTRY
    assert LLM_REGISTRY == {}


def test_chunking_registry_has_fixed_size() -> None:
    """fixed_size registered in Story 4.1."""
    assert "fixed_size" in CHUNKING_REGISTRY
    assert CHUNKING_REGISTRY["fixed_size"] is FixedSizeChunker


def test_reranker_registry_has_exactly_one_entry() -> None:
    """Only 'none' is registered in Story 1.8; Epic 7 adds more."""
    assert len(RERANKER_REGISTRY) == 1
