from datetime import UTC, datetime

from beanie import Document
from pydantic import Field

from app.models.document import DocumentStatus


class IngestionJob(Document):
    job_id: str
    document_id: str
    tenant_id: str
    status: DocumentStatus = DocumentStatus.queued
    error_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "ingestion_jobs"
        indexes = ["job_id", "document_id"]
