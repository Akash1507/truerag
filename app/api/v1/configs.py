from fastapi import APIRouter
from pydantic import BaseModel

from app.providers.registry import (
    CHUNKING_REGISTRY,
    EMBEDDING_REGISTRY,
    LLM_REGISTRY,
    RERANKER_REGISTRY,
    VECTOR_STORE_REGISTRY,
)

router = APIRouter()


class ConfigOption(BaseModel):
    value: str
    label: str


class PlatformConfigResponse(BaseModel):
    llm_providers: list[ConfigOption]
    embedding_providers: list[ConfigOption]
    vector_stores: list[ConfigOption]
    chunking_strategies: list[ConfigOption]
    retrieval_modes: list[ConfigOption]
    rerankers: list[ConfigOption]


_LLM_LABELS: dict[str, str] = {
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI GPT",
    "bedrock": "AWS Bedrock",
}
_EMBEDDING_LABELS: dict[str, str] = {
    "openai": "OpenAI Embeddings",
    "cohere": "Cohere Embeddings",
    "bedrock": "AWS Bedrock Embeddings",
}
_VECTOR_STORE_LABELS: dict[str, str] = {
    "pgvector": "PostgreSQL pgvector",
    "qdrant": "Qdrant",
    "pinecone": "Pinecone",
}
_CHUNKING_LABELS: dict[str, str] = {
    "fixed_size": "Fixed Size",
    "semantic": "Semantic",
    "hierarchical": "Hierarchical",
    "document_aware": "Document Aware",
    "keyword": "Keyword",
}
_RETRIEVAL_MODE_LABELS: dict[str, str] = {
    "dense": "Dense (Vector)",
    "sparse": "Sparse (BM25)",
    "hybrid": "Hybrid (Dense + Sparse)",
}
_RERANKER_LABELS: dict[str, str] = {
    "none": "None (Passthrough)",
    "cross_encoder": "Cross Encoder",
    "cohere": "Cohere Rerank",
}


def _options(registry: dict, labels: dict[str, str]) -> list[ConfigOption]:
    return [ConfigOption(value=k, label=labels.get(k, k.replace("_", " ").title())) for k in registry]


@router.get("", response_model=PlatformConfigResponse)
async def get_platform_configs() -> PlatformConfigResponse:
    retrieval_modes = [
        ConfigOption(value=k, label=v) for k, v in _RETRIEVAL_MODE_LABELS.items()
    ]
    return PlatformConfigResponse(
        llm_providers=_options(LLM_REGISTRY, _LLM_LABELS),
        embedding_providers=_options(EMBEDDING_REGISTRY, _EMBEDDING_LABELS),
        vector_stores=_options(VECTOR_STORE_REGISTRY, _VECTOR_STORE_LABELS),
        chunking_strategies=_options(CHUNKING_REGISTRY, _CHUNKING_LABELS),
        retrieval_modes=retrieval_modes,
        rerankers=_options(RERANKER_REGISTRY, _RERANKER_LABELS),
    )
