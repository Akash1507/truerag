from datetime import datetime
from enum import StrEnum

from beanie import Document
from pydantic import BaseModel


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
    status: DocumentStatus
    error_reason: str | None = None
    created_at: datetime

    class Settings:
        name = "documents"


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
