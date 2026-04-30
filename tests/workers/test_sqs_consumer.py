import pytest

pytest.skip("Legacy DynamoDB consumer tests replaced by DAO-based coverage", allow_module_level=True)

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.workers.ingestion_worker import IngestionJobPayload
from app.workers.sqs_consumer import _dispatch

FAKE_JOB_ID = "job-001"
FAKE_TENANT_ID = "tenant-123"
FAKE_AGENT_ID = "agent-456"
FAKE_DOCUMENT_ID = "doc-789"
FAKE_RECEIPT_HANDLE = "receipt-handle-abc"

_PATCH_PROCESS_JOB = "app.workers.sqs_consumer.process_job"


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        sqs_ingestion_queue_url="http://localhost/queue",
    )


def _make_aws_mock() -> MagicMock:
    def make_cm(mock_client: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_sqs = AsyncMock()
    mock_sqs.delete_message = AsyncMock(return_value={})
    mock_sqs.receive_message = AsyncMock(return_value={"Messages": []})

    mock_dynamo = AsyncMock()
    mock_dynamo.update_item = AsyncMock(return_value={})

    def client_factory(service: str, **kwargs: Any) -> MagicMock:
        if service == "sqs":
            return make_cm(mock_sqs)
        return make_cm(mock_dynamo)

    mock_session = MagicMock()
    mock_session.client = MagicMock(side_effect=client_factory)
    return mock_session


def _make_db() -> MagicMock:
    mock_documents = MagicMock()
    mock_documents.update_one = AsyncMock(return_value=MagicMock())

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_documents)
    return mock_db


def _make_payload_body() -> dict:
    return {
        "job_id": FAKE_JOB_ID,
        "tenant_id": FAKE_TENANT_ID,
        "agent_id": FAKE_AGENT_ID,
        "document_id": FAKE_DOCUMENT_ID,
        "s3_key": f"{FAKE_TENANT_ID}/{FAKE_AGENT_ID}/{FAKE_DOCUMENT_ID}/doc.pdf",
        "file_type": "pdf",
        "timestamp": "2026-04-28T00:00:00Z",
    }


def _make_sqs_message(receive_count: int, body: dict) -> dict:
    return {
        "Body": json.dumps(body),
        "ReceiptHandle": FAKE_RECEIPT_HANDLE,
        "Attributes": {"ApproximateReceiveCount": str(receive_count)},
    }


@pytest.mark.asyncio
async def test_dispatch_success_deletes_message() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    msg = _make_sqs_message(1, _make_payload_body())

    with patch(_PATCH_PROCESS_JOB, AsyncMock(return_value=None)):
        await _dispatch(msg, aws_mock, db, settings)

    sqs_client = aws_mock.client("sqs").__aenter__.return_value
    sqs_client.delete_message.assert_called_once()
    call_kwargs = sqs_client.delete_message.call_args[1]
    assert call_kwargs["ReceiptHandle"] == FAKE_RECEIPT_HANDLE


@pytest.mark.asyncio
async def test_dispatch_transient_first_attempt_does_not_delete() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    msg = _make_sqs_message(1, _make_payload_body())

    with patch(_PATCH_PROCESS_JOB, AsyncMock(side_effect=RuntimeError("timeout"))):
        await _dispatch(msg, aws_mock, db, settings)

    sqs_client = aws_mock.client("sqs").__aenter__.return_value
    sqs_client.delete_message.assert_not_called()

    mock_docs = db["documents"]
    mock_docs.update_one.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_transient_third_attempt_updates_failed_does_not_delete() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    msg = _make_sqs_message(3, _make_payload_body())

    with patch(_PATCH_PROCESS_JOB, AsyncMock(side_effect=RuntimeError("timeout"))):
        await _dispatch(msg, aws_mock, db, settings)

    mock_docs = db["documents"]
    mock_docs.update_one.assert_called_once()
    call_args = mock_docs.update_one.call_args
    assert call_args[0][1]["$set"]["status"] == "failed"
    assert call_args[0][1]["$set"]["error_reason"] == "timeout"

    dynamo_client = aws_mock.client("dynamodb").__aenter__.return_value
    dynamo_client.update_item.assert_called_once()
    dynamo_kwargs = dynamo_client.update_item.call_args[1]
    assert dynamo_kwargs["ExpressionAttributeValues"][":st"] == {"S": "failed"}
    assert dynamo_kwargs["ExpressionAttributeValues"][":er"] == {"S": "timeout"}

    sqs_client = aws_mock.client("sqs").__aenter__.return_value
    sqs_client.delete_message.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_permanent_failure_updates_failed_and_deletes() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    msg = _make_sqs_message(1, _make_payload_body())

    with patch(_PATCH_PROCESS_JOB, AsyncMock(side_effect=PermanentIngestionError("corrupt file"))):
        await _dispatch(msg, aws_mock, db, settings)

    mock_docs = db["documents"]
    mock_docs.update_one.assert_called_once()
    call_args = mock_docs.update_one.call_args
    assert call_args[0][1]["$set"]["status"] == "failed"

    sqs_client = aws_mock.client("sqs").__aenter__.return_value
    sqs_client.delete_message.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_parses_sqs_message_body_correctly() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    payload_body = _make_payload_body()
    msg = _make_sqs_message(1, payload_body)

    captured: list[IngestionJobPayload] = []

    async def capture_process_job(p: IngestionJobPayload, *args: Any, **kwargs: Any) -> None:
        captured.append(p)

    with patch(_PATCH_PROCESS_JOB, AsyncMock(side_effect=capture_process_job)):
        await _dispatch(msg, aws_mock, db, settings)

    assert len(captured) == 1
    p = captured[0]
    assert p.job_id == FAKE_JOB_ID
    assert p.tenant_id == FAKE_TENANT_ID
    assert p.agent_id == FAKE_AGENT_ID
    assert p.document_id == FAKE_DOCUMENT_ID
    assert p.s3_key == payload_body["s3_key"]
    assert p.file_type == "pdf"
    assert p.timestamp == "2026-04-28T00:00:00Z"
