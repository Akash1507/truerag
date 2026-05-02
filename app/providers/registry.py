from app.interfaces.chunking_strategy import ChunkingStrategy
from app.interfaces.embedding_provider import EmbeddingProvider
from app.interfaces.llm_provider import LLMProvider
from app.interfaces.reranker import Reranker
from app.interfaces.vector_store import VectorStore
from app.providers.chunking.document_aware import DocumentAwareChunker
from app.providers.chunking.fixed_size import FixedSizeChunker
from app.providers.chunking.hierarchical import HierarchicalChunker
from app.providers.chunking.keyword import KeywordChunker
from app.providers.chunking.semantic import SemanticChunker
from app.providers.embedding.bedrock import BedrockEmbedder
from app.providers.embedding.cohere import CohereEmbedder
from app.providers.embedding.openai import OpenAIEmbedder
from app.providers.llm.anthropic import AnthropicLLMProvider
from app.providers.llm.bedrock import BedrockLLMProvider
from app.providers.llm.openai import OpenAILLMProvider
from app.providers.rerankers.cohere import CohereReranker
from app.providers.rerankers.cross_encoder import CrossEncoderReranker
from app.providers.rerankers.passthrough import PassthroughReranker
from app.providers.vector_stores.pinecone import PineconeVectorStore
from app.providers.vector_stores.pgvector import PgVectorStore
from app.providers.vector_stores.qdrant import QdrantVectorStore

VECTOR_STORE_REGISTRY: dict[str, type[VectorStore]] = {
    "pgvector": PgVectorStore,
    "qdrant": QdrantVectorStore,
    "pinecone": PineconeVectorStore,
}

CHUNKING_REGISTRY: dict[str, type[ChunkingStrategy]] = {
    "fixed_size": FixedSizeChunker,
    "semantic": SemanticChunker,
    "hierarchical": HierarchicalChunker,
    "document_aware": DocumentAwareChunker,
    "keyword": KeywordChunker,
}

RERANKER_REGISTRY: dict[str, type[Reranker]] = {
    "none": PassthroughReranker,
    "cross_encoder": CrossEncoderReranker,
    "cohere": CohereReranker,
}

EMBEDDING_REGISTRY: dict[str, type[EmbeddingProvider]] = {
    "openai": OpenAIEmbedder,
    "cohere": CohereEmbedder,
    "bedrock": BedrockEmbedder,
}

LLM_REGISTRY: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicLLMProvider,
    "openai": OpenAILLMProvider,
    "bedrock": BedrockLLMProvider,
}
