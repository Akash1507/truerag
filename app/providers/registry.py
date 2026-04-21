from app.interfaces.chunking_strategy import ChunkingStrategy
from app.interfaces.embedding_provider import EmbeddingProvider
from app.interfaces.llm_provider import LLMProvider
from app.interfaces.reranker import Reranker
from app.interfaces.vector_store import VectorStore
from app.providers.rerankers.passthrough import PassthroughReranker

VECTOR_STORE_REGISTRY: dict[str, type[VectorStore]] = {
    # Populated in later epics: "pgvector": PgVectorStore, "qdrant": ..., "pinecone": ...
}

CHUNKING_REGISTRY: dict[str, type[ChunkingStrategy]] = {
    # Populated in Epic 4: "fixed_size": FixedSizeChunker, ...
}

RERANKER_REGISTRY: dict[str, type[Reranker]] = {
    "none": PassthroughReranker,
    # Populated in Epic 7: "cross_encoder": ..., "cohere": ...
}

EMBEDDING_REGISTRY: dict[str, type[EmbeddingProvider]] = {
    # Populated in Epic 4: "openai": OpenAIEmbedder, ...
}

LLM_REGISTRY: dict[str, type[LLMProvider]] = {
    # Populated in Epic 5: "anthropic": AnthropicProvider, ...
}
