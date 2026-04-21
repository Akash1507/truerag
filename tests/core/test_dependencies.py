import pytest

from app.core.dependencies import (
    get_chunker,
    get_embedder,
    get_llm_provider,
    get_reranker,
    get_vector_store,
)
from app.core.errors import ProviderUnavailableError
from app.providers.rerankers.passthrough import PassthroughReranker


def test_get_reranker_none_returns_passthrough() -> None:
    result = get_reranker("none")
    assert isinstance(result, PassthroughReranker)


def test_get_reranker_unknown_raises_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError, match="Unknown reranker.*unknown"):
        get_reranker("unknown")


def test_get_vector_store_unknown_raises_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError, match="Unknown vector store provider.*pgvector"):
        get_vector_store("pgvector")


def test_get_chunker_unknown_raises_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError, match="Unknown chunking strategy.*fixed"):
        get_chunker("fixed")


def test_get_embedder_unknown_raises_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError, match="Unknown embedding provider.*openai"):
        get_embedder("openai")


def test_get_llm_provider_unknown_raises_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError, match="Unknown LLM provider.*anthropic"):
        get_llm_provider("anthropic")
