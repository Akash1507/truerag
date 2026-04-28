import json
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import UploadFile

from app.core.config import Settings
from app.core.errors import IngestionError, UnsupportedFileTypeError
from app.models.document import DocumentUploadResponse
from app.services.ingestion_service import upload_document

FAKE_TENANT_ID = "tenant-123"
FAKE_AGENT_ID = str(ObjectId())

FAKE_AGENT_DOC = MagicMock()
FAKE_AGENT_DOC.agent_id = FAKE_AGENT_ID
FAKE_AGENT_DOC.tenant_id = FAKE_TENANT_ID

_PATCH_GET_AGENT = "app.services.ingestion_service.agent_service.get_agent"


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        dynamodb_jobs_table="test-jobs",
        sqs_ingestion_queue_url="http://localhost/queue",
    )


def _make_upload_file(filename: str, content: bytes = b"PDF content") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


def _make_aws_mock(
    sqs_send_side_effect: Exception | None = None,
    dynamo_put_side_effect: Exception | None = None,
) -> MagicMock:
    def make_cm(mock_client: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_s3 = AsyncMock()
    mock_s3.put_object = AsyncMock(return_value={})
    mock_s3.delete_object = AsyncMock(return_value={})

    mock_sqs = AsyncMock()
    mock_sqs.send_message = AsyncMock(side_effect=sqs_send_side_effect)

    mock_dynamo = AsyncMock()
    mock_dynamo.put_item = AsyncMock(side_effect=dynamo_put_side_effect)
    mock_dynamo.update_item = AsyncMock(return_value={})

    def client_factory(service: str, **kwargs: Any) -> MagicMock:
        if service == "s3":
            return make_cm(mock_s3)
        if service == "sqs":
            return make_cm(mock_sqs)
        return make_cm(mock_dynamo)

    mock_session = MagicMock()
    mock_session.client = MagicMock(side_effect=client_factory)
    return mock_session


def _make_db(insert_side_effect: Exception | None = None) -> MagicMock:
    mock_documents = MagicMock()
    if insert_side_effect is not None:
        mock_documents.insert_one = AsyncMock(side_effect=insert_side_effect)
    else:
        mock_documents.insert_one = AsyncMock(return_value=MagicMock(inserted_id="oid"))
    mock_documents.update_one = AsyncMock(return_value=MagicMock())
    mock_documents.delete_one = AsyncMock(return_value=MagicMock())

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_documents)
    return mock_db


@pytest.mark.asyncio
async def test_upload_document_success() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    file = _make_upload_file("report.pdf")

    with patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)):
        result = await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    assert isinstance(result, DocumentUploadResponse)
    assert result.status == "queued"
    mock_docs = db["documents"]
    mock_docs.insert_one.assert_called_once()
    call_kwargs = mock_docs.insert_one.call_args[0][0]
    assert call_kwargs["status"] == "queued"
    assert call_kwargs["tenant_id"] == FAKE_TENANT_ID
    assert call_kwargs["agent_id"] == FAKE_AGENT_ID
    assert call_kwargs["file_type"] == "pdf"


@pytest.mark.asyncio
async def test_upload_document_s3_key_format() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    filename = "report.pdf"
    file = _make_upload_file(filename)

    with patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)):
        result = await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    mock_docs = db["documents"]
    call_kwargs = mock_docs.insert_one.call_args[0][0]
    document_id = call_kwargs["document_id"]
    expected_key = f"{FAKE_TENANT_ID}/{FAKE_AGENT_ID}/{document_id}/{filename}"
    assert call_kwargs["s3_key"] == expected_key
    assert result.document_id == document_id


@pytest.mark.asyncio
async def test_upload_document_sqs_message_format() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    file = _make_upload_file("doc.txt")

    with patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)):
        await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    sqs_cm = aws_mock.client("sqs")
    sqs_client = sqs_cm.__aenter__.return_value
    sqs_client.send_message.assert_called_once()
    call_kwargs = sqs_client.send_message.call_args[1]
    msg = json.loads(call_kwargs["MessageBody"])
    expected_fields = (
        "job_id", "tenant_id", "agent_id", "document_id", "s3_key", "file_type", "timestamp"
    )
    for field in expected_fields:
        assert field in msg, f"Missing field: {field}"
    assert msg["tenant_id"] == FAKE_TENANT_ID
    assert msg["agent_id"] == FAKE_AGENT_ID
    assert msg["file_type"] == "txt"


@pytest.mark.asyncio
async def test_upload_document_unsupported_type_xlsx() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    file = _make_upload_file("spreadsheet.xlsx")

    with (
        patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)),
        pytest.raises(UnsupportedFileTypeError),
    ):
        await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    s3_cm = aws_mock.client("s3")
    s3_client = s3_cm.__aenter__.return_value
    s3_client.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_upload_document_unsupported_type_no_extension() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    file = _make_upload_file("Makefile")

    with (
        patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)),
        pytest.raises(UnsupportedFileTypeError),
    ):
        await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )


@pytest.mark.asyncio
async def test_upload_document_sqs_failure_marks_both_failed() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock(sqs_send_side_effect=RuntimeError("queue down"))
    settings = _make_settings()
    file = _make_upload_file("report.pdf")

    with (
        patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)),
        pytest.raises(IngestionError),
    ):
        await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    mock_docs = db["documents"]
    mock_docs.update_one.assert_called_once()
    update_args = mock_docs.update_one.call_args[0]
    assert update_args[1]["$set"]["status"] == "failed"
    assert "error_reason" in update_args[1]["$set"]

    dynamo_cm = aws_mock.client("dynamodb")
    dynamo_client = dynamo_cm.__aenter__.return_value
    dynamo_client.update_item.assert_called()


@pytest.mark.asyncio
async def test_upload_document_returns_correct_response() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    file = _make_upload_file("notes.md")

    with patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)):
        result = await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    assert result.status == "queued"
    assert len(result.job_id) > 0
    assert len(result.document_id) > 0


@pytest.mark.asyncio
async def test_upload_document_mongo_insert_failure_compensates_s3() -> None:
    db = _make_db(insert_side_effect=RuntimeError("mongo down"))
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    file = _make_upload_file("report.pdf")

    with (
        patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)),
        pytest.raises(IngestionError),
    ):
        await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    s3_client = aws_mock.client("s3").__aenter__.return_value
    s3_client.delete_object.assert_called_once()
    assert s3_client.delete_object.call_args.kwargs["Bucket"] == settings.s3_document_bucket


@pytest.mark.asyncio
async def test_upload_document_dynamo_put_failure_compensates_s3_and_mongo() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock(dynamo_put_side_effect=RuntimeError("dynamo down"))
    settings = _make_settings()
    file = _make_upload_file("report.pdf")

    with (
        patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)),
        pytest.raises(IngestionError),
    ):
        await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    s3_client = aws_mock.client("s3").__aenter__.return_value
    s3_client.delete_object.assert_called_once()

    mock_docs = db["documents"]
    mock_docs.delete_one.assert_called_once()
    assert mock_docs.delete_one.call_args[0][0].get("document_id") is not None


@pytest.mark.asyncio
async def test_upload_document_file_too_large_rejected_before_s3() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    big_content = b"x" * (50 * 1024 * 1024 + 1)
    file = _make_upload_file("big.pdf", content=big_content)

    with (
        patch(_PATCH_GET_AGENT, AsyncMock(return_value=FAKE_AGENT_DOC)),
        pytest.raises(IngestionError),
    ):
        await upload_document(
            file=file,
            agent_id=FAKE_AGENT_ID,
            tenant_id=FAKE_TENANT_ID,
            db=db,
            aws_session=aws_mock,
            settings=settings,
        )

    s3_client = aws_mock.client("s3").__aenter__.return_value
    s3_client.put_object.assert_not_called()
