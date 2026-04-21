from app.providers.registry import (
    CHUNKING_REGISTRY,
    EMBEDDING_REGISTRY,
    LLM_REGISTRY,
    RERANKER_REGISTRY,
    VECTOR_STORE_REGISTRY,
)
from app.providers.rerankers.passthrough import PassthroughReranker


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


def test_empty_registries_are_dicts() -> None:
    """Registries not yet populated should be empty dicts, not None or missing."""
    assert VECTOR_STORE_REGISTRY == {}
    assert CHUNKING_REGISTRY == {}
    assert EMBEDDING_REGISTRY == {}
    assert LLM_REGISTRY == {}


def test_reranker_registry_has_exactly_one_entry() -> None:
    """Only 'none' is registered in Story 1.8; Epic 7 adds more."""
    assert len(RERANKER_REGISTRY) == 1
