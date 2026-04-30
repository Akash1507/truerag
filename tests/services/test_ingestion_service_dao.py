import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from app.core.config import Settings
from app.core.errors import DocumentNotFoundError, ForbiddenError, IngestionError, UnsupportedFileTypeError
from app.models.document import DocumentRecord, DocumentStatus
from app.models.ingestion_job import IngestionJob
from app.services import ingestion_service

TENANT_ID = "tenant-123"
AGENT_ID = "507f1f77bcf86cd799439011"


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        sqs_ingestion_queue_url="http://localhost/queue",
    )


def _make_upload_file(filename: str, content: bytes = b"PDF content") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


def _make_aws_mock(sqs_side_effect: Exception | None = None) -> MagicMock:
    def make_cm(client: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    s3 = AsyncMock()
    s3.put_object = AsyncMock(return_value={})
    s3.delete_object = AsyncMock(return_value={})
    sqs = AsyncMock()
    sqs.send_message = AsyncMock(side_effect=sqs_side_effect)

    session = MagicMock()
    session.client = MagicMock(
        side_effect=lambda service, **kwargs: make_cm(s3 if service == "s3" else sqs)
    )
    return session


def _make_document(**overrides: object) -> DocumentRecord:
    base: dict[str, object] = {
        "document_id": "doc-1",
        "agent_id": AGENT_ID,
        "tenant_id": TENANT_ID,
        "filename": "report.pdf",
        "file_type": "pdf",
        "s3_key": "tenant/agent/doc.pdf",
        "job_id": "job-1",
        "status": DocumentStatus.queued,
        "error_reason": None,
        "created_at": ingestion_service.datetime.now(ingestion_service.UTC),
    }
    base.update(overrides)
    return DocumentRecord(**base)


@pytest.mark.asyncio
async def test_upload_document_success() -> None:
    aws = _make_aws_mock()
    with patch("app.services.ingestion_service.agent_service.get_agent", AsyncMock(return_value=MagicMock())), patch.object(
        ingestion_service.document_dao, "insert_one", AsyncMock()
    ) as insert_doc, patch.object(ingestion_service.ingestion_job_dao, "insert_one", AsyncMock()) as insert_job:
        result = await ingestion_service.upload_document(
            _make_upload_file("report.pdf"),
            AGENT_ID,
            TENANT_ID,
            aws,
            _make_settings(),
        )

    assert result.status == "queued"
    insert_doc.assert_awaited_once()
    insert_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_document_rejects_unsupported_type() -> None:
    with patch("app.services.ingestion_service.agent_service.get_agent", AsyncMock(return_value=MagicMock())):
        with pytest.raises(UnsupportedFileTypeError):
            await ingestion_service.upload_document(
                _make_upload_file("report.xlsx"),
                AGENT_ID,
                TENANT_ID,
                _make_aws_mock(),
                _make_settings(),
            )


@pytest.mark.asyncio
async def test_upload_document_marks_failed_on_sqs_error() -> None:
    aws = _make_aws_mock(sqs_side_effect=RuntimeError("queue error"))
    with patch("app.services.ingestion_service.agent_service.get_agent", AsyncMock(return_value=MagicMock())), patch.object(
        ingestion_service.document_dao, "insert_one", AsyncMock()
    ), patch.object(ingestion_service.ingestion_job_dao, "insert_one", AsyncMock()), patch.object(
        ingestion_service.document_dao, "update", AsyncMock()
    ) as update_doc, patch.object(ingestion_service.ingestion_job_dao, "update", AsyncMock()) as update_job:
        with pytest.raises(IngestionError):
            await ingestion_service.upload_document(
                _make_upload_file("report.pdf"),
                AGENT_ID,
                TENANT_ID,
                aws,
                _make_settings(),
            )

    update_doc.assert_awaited_once()
    update_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_document_status_prefers_job_record() -> None:
    with patch.object(
        ingestion_service.document_dao,
        "find_one",
        AsyncMock(return_value=_make_document()),
    ), patch.object(
        ingestion_service.ingestion_job_dao,
        "find_one",
        AsyncMock(return_value=IngestionJob(job_id="job-1", document_id="doc-1", tenant_id=TENANT_ID, status="processing")),
    ):
        result = await ingestion_service.get_document_status("doc-1", AGENT_ID, TENANT_ID)

    assert result.status == "processing"


@pytest.mark.asyncio
async def test_get_document_status_not_found() -> None:
    with patch.object(ingestion_service.document_dao, "find_one", AsyncMock(return_value=None)):
        with pytest.raises(DocumentNotFoundError):
            await ingestion_service.get_document_status("missing", AGENT_ID, TENANT_ID)


@pytest.mark.asyncio
async def test_get_document_status_forbidden() -> None:
    with patch.object(
        ingestion_service.document_dao,
        "find_one",
        AsyncMock(return_value=_make_document(tenant_id="other-tenant")),
    ):
        with pytest.raises(ForbiddenError):
            await ingestion_service.get_document_status("doc-1", AGENT_ID, TENANT_ID)


@pytest.mark.asyncio
async def test_list_documents_returns_page() -> None:
    docs = [
        _make_document(document_id="doc-1"),
        _make_document(document_id="doc-2"),
        _make_document(document_id="doc-3"),
    ]
    for idx, doc in enumerate(docs, start=1):
        doc.id = ingestion_service.ObjectId(f"507f1f77bcf86cd7994390{20+idx}")

    with patch("app.services.ingestion_service.agent_service.get_agent", AsyncMock(return_value=MagicMock())), patch.object(
        ingestion_service.document_dao, "find", AsyncMock(return_value=docs)
    ):
        items, next_cursor = await ingestion_service.list_documents(AGENT_ID, TENANT_ID, limit=2)

    assert len(items) == 2
    assert next_cursor is not None
