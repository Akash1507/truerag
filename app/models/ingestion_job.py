from dataclasses import dataclass
from datetime import UTC, datetime

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.models.document import DocumentStatus


@dataclass
class IngestionJobPayload:
    job_id: str
    tenant_id: str
    agent_id: str
    document_id: str
    s3_key: str
    file_type: str
    timestamp: str


class IngestionJob(Document):
    job_id: str
    document_id: str
    tenant_id: str
    status: DocumentStatus = DocumentStatus.queued
    error_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "ingestion_jobs"
        indexes = [
            IndexModel([("job_id", ASCENDING)]),
            IndexModel([("document_id", ASCENDING)]),
        ]
