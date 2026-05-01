from app.interfaces.chunking_strategy import ChunkingStrategy
from app.interfaces.embedding_provider import EmbeddingProvider
from app.interfaces.llm_provider import LLMProvider
from app.interfaces.reranker import Reranker
from app.interfaces.vector_store import VectorStore
from app.providers.chunking.fixed_size import FixedSizeChunker
from app.providers.embedding.openai import OpenAIEmbedder
from app.providers.rerankers.passthrough import PassthroughReranker
from app.providers.vector_stores.pgvector import PgVectorStore

VECTOR_STORE_REGISTRY: dict[str, type[VectorStore]] = {
    "pgvector": PgVectorStore,
}

CHUNKING_REGISTRY: dict[str, type[ChunkingStrategy]] = {
    "fixed_size": FixedSizeChunker,
}

RERANKER_REGISTRY: dict[str, type[Reranker]] = {
    "none": PassthroughReranker,
    # Populated in Epic 7: "cross_encoder": ..., "cohere": ...
}

EMBEDDING_REGISTRY: dict[str, type[EmbeddingProvider]] = {
    "openai": OpenAIEmbedder,
}

LLM_REGISTRY: dict[str, type[LLMProvider]] = {
    # Populated in Epic 5: "anthropic": AnthropicProvider, ...
}
