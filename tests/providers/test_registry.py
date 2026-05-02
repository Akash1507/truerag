from app.providers.chunking.fixed_size import FixedSizeChunker
from app.providers.registry import (
    CHUNKING_REGISTRY,
    EMBEDDING_REGISTRY,
    LLM_REGISTRY,
    RERANKER_REGISTRY,
    VECTOR_STORE_REGISTRY,
)
from app.providers.rerankers.cohere import CohereReranker
from app.providers.rerankers.cross_encoder import CrossEncoderReranker
from app.providers.rerankers.passthrough import PassthroughReranker
from app.providers.llm.anthropic import AnthropicLLMProvider
from app.providers.embedding.bedrock import BedrockEmbedder
from app.providers.embedding.cohere import CohereEmbedder
from app.providers.llm.bedrock import BedrockLLMProvider
from app.providers.llm.openai import OpenAILLMProvider
from app.providers.vector_stores.pinecone import PineconeVectorStore
from app.providers.vector_stores.pgvector import PgVectorStore
from app.providers.vector_stores.qdrant import QdrantVectorStore


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
    """Current stories register pgvector/qdrant/pinecone and multi-embed providers."""
    assert VECTOR_STORE_REGISTRY == {
        "pgvector": PgVectorStore,
        "qdrant": QdrantVectorStore,
        "pinecone": PineconeVectorStore,
    }
    assert EMBEDDING_REGISTRY["cohere"] is CohereEmbedder
    assert EMBEDDING_REGISTRY["bedrock"] is BedrockEmbedder
    assert "openai" in EMBEDDING_REGISTRY
    assert LLM_REGISTRY == {
        "anthropic": AnthropicLLMProvider,
        "openai": OpenAILLMProvider,
        "bedrock": BedrockLLMProvider,
    }


def test_chunking_registry_has_fixed_size() -> None:
    """fixed_size registered in Story 4.1."""
    assert "fixed_size" in CHUNKING_REGISTRY
    assert CHUNKING_REGISTRY["fixed_size"] is FixedSizeChunker


def test_reranker_registry_has_expected_entries() -> None:
    assert RERANKER_REGISTRY["none"] is PassthroughReranker
    assert RERANKER_REGISTRY["cross_encoder"] is CrossEncoderReranker
    assert RERANKER_REGISTRY["cohere"] is CohereReranker
