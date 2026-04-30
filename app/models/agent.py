from datetime import datetime
from typing import Annotated

from beanie import Document
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

VALID_CHUNKING_STRATEGIES: frozenset[str] = frozenset(
    {"fixed_size", "semantic", "hierarchical", "document_aware"}
)
VALID_VECTOR_STORES: frozenset[str] = frozenset({"pgvector", "qdrant", "pinecone"})
VALID_EMBEDDING_PROVIDERS: frozenset[str] = frozenset({"openai", "cohere", "bedrock"})
VALID_LLM_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai", "bedrock"})
VALID_RETRIEVAL_MODES: frozenset[str] = frozenset({"dense", "sparse", "hybrid"})
VALID_RERANKERS: frozenset[str] = frozenset({"none", "cross_encoder", "cohere"})


class AgentDocument(Document):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    agent_id: str
    tenant_id: str
    name: str
    chunking_strategy: str
    vector_store: str
    embedding_provider: str
    llm_provider: str
    retrieval_mode: str
    reranker: str
    top_k: int
    semantic_cache_enabled: bool
    semantic_cache_threshold: float | None
    status: str
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "agents"


AgentName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=100,
        strip_whitespace=True,
        pattern=r"^[a-zA-Z0-9_-]+$",
    ),
]


class AgentCreateRequest(BaseModel):
    name: AgentName
    chunking_strategy: str
    vector_store: str
    embedding_provider: str
    llm_provider: str
    retrieval_mode: str
    reranker: str
    top_k: int = Field(ge=1, le=100)
    tenant_id: str | None = None
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class AgentCreateResponse(BaseModel):
    agent_id: str
    tenant_id: str
    name: str
    chunking_strategy: str
    vector_store: str
    embedding_provider: str
    llm_provider: str
    retrieval_mode: str
    reranker: str
    top_k: int
    semantic_cache_enabled: bool
    semantic_cache_threshold: float | None
    status: str
    created_at: datetime
    updated_at: datetime


class AgentConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunking_strategy: str | None = None
    vector_store: str | None = None
    embedding_provider: str | None = None
    llm_provider: str | None = None
    retrieval_mode: str | None = None
    reranker: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)
    semantic_cache_enabled: bool | None = None
    semantic_cache_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class AgentListResponse(BaseModel):
    items: list[AgentCreateResponse]
    next_cursor: str | None


class AgentUpdateResponse(BaseModel):
    agent_id: str
    tenant_id: str
    name: str
    chunking_strategy: str
    vector_store: str
    embedding_provider: str
    llm_provider: str
    retrieval_mode: str
    reranker: str
    top_k: int
    semantic_cache_enabled: bool
    semantic_cache_threshold: float | None
    status: str
    created_at: datetime
    updated_at: datetime
    warnings: list[str]
