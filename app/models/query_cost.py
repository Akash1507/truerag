from datetime import UTC, datetime

from beanie import Document
from pydantic import Field


class QueryCost(Document):
    tenant_id: str
    agent_id: str
    request_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_calls: int = 0
    reranker_calls: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "query_costs"
        indexes = [("tenant_id", 1), ("agent_id", 1), ("timestamp", -1)]
