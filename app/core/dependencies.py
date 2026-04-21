from app.core.errors import ProviderUnavailableError
from app.interfaces.chunking_strategy import ChunkingStrategy
from app.interfaces.embedding_provider import EmbeddingProvider
from app.interfaces.llm_provider import LLMProvider
from app.interfaces.reranker import Reranker
from app.interfaces.vector_store import VectorStore
from app.providers.registry import (
    CHUNKING_REGISTRY,
    EMBEDDING_REGISTRY,
    LLM_REGISTRY,
    RERANKER_REGISTRY,
    VECTOR_STORE_REGISTRY,
)


def get_vector_store(vector_store_key: str) -> VectorStore:
    cls = VECTOR_STORE_REGISTRY.get(vector_store_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown vector store provider: {vector_store_key!r}"
        )
    return cls()


def get_chunker(chunking_key: str) -> ChunkingStrategy:
    cls = CHUNKING_REGISTRY.get(chunking_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown chunking strategy: {chunking_key!r}"
        )
    return cls()


def get_reranker(reranker_key: str) -> Reranker:
    cls = RERANKER_REGISTRY.get(reranker_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown reranker: {reranker_key!r}"
        )
    return cls()


def get_embedder(embedding_key: str) -> EmbeddingProvider:
    cls = EMBEDDING_REGISTRY.get(embedding_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown embedding provider: {embedding_key!r}"
        )
    return cls()


def get_llm_provider(llm_key: str) -> LLMProvider:
    cls = LLM_REGISTRY.get(llm_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown LLM provider: {llm_key!r}"
        )
    return cls()
