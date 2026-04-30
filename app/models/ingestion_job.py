from datetime import UTC, datetime
from typing import ClassVar

from beanie import Document
from pydantic import Field


class IngestionJob(Document):
    job_id: str
    document_id: str
    tenant_id: str
    status: str = "queued"
    error_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "ingestion_jobs"
        indexes: ClassVar[list[str]] = ["job_id", "document_id"]
