from datetime import datetime
from enum import StrEnum

from beanie import Document
from pydantic import BaseModel
from pymongo import ASCENDING, IndexModel


class DocumentStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class DocumentRecord(Document):
    document_id: str
    agent_id: str
    tenant_id: str
    filename: str
    file_type: str
    s3_key: str
    job_id: str | None = None
    version: int = 1
    content_hash: str | None = None
    lineage_id: str | None = None
    archived_at: datetime | None = None
    superseded_by_document_id: str | None = None
    status: DocumentStatus
    error_reason: str | None = None
    created_at: datetime

    class Settings:
        name = "documents"
        indexes = [
            IndexModel(
                [
                    ("tenant_id", ASCENDING),
                    ("agent_id", ASCENDING),
                    ("archived_at", ASCENDING),
                    ("content_hash", ASCENDING),
                    ("created_at", ASCENDING),
                ]
            ),
            IndexModel(
                [("lineage_id", ASCENDING), ("version", ASCENDING), ("created_at", ASCENDING)]
            ),
            IndexModel(
                [("tenant_id", ASCENDING), ("agent_id", ASCENDING), ("archived_at", ASCENDING)]
            ),
        ]


class DocumentUploadResponse(BaseModel):
    job_id: str
    document_id: str
    status: str = "queued"


class DocumentStatusResponse(BaseModel):
    document_id: str
    status: DocumentStatus
    error_reason: str | None = None


class DocumentListItem(BaseModel):
    document_id: str
    filename: str
    file_type: str
    status: DocumentStatus
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None = None


class ReindexResponse(BaseModel):
    enqueued_count: int
