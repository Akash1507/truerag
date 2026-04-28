from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.workers.ingestion_worker import IngestionJobPayload, process_job

FAKE_JOB_ID = "job-001"
FAKE_TENANT_ID = "tenant-123"
FAKE_AGENT_ID = "agent-456"
FAKE_DOCUMENT_ID = "doc-789"

_PATCH_STUB = "app.workers.ingestion_worker._run_pipeline_stub"


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        dynamodb_jobs_table="test-jobs",
        sqs_ingestion_queue_url="http://localhost/queue",
    )


def _make_aws_mock() -> MagicMock:
    def make_cm(mock_client: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_sqs = AsyncMock()
    mock_sqs.send_message = AsyncMock(return_value={})
    mock_sqs.delete_message = AsyncMock(return_value={})

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


def _make_payload() -> IngestionJobPayload:
    return IngestionJobPayload(
        job_id=FAKE_JOB_ID,
        tenant_id=FAKE_TENANT_ID,
        agent_id=FAKE_AGENT_ID,
        document_id=FAKE_DOCUMENT_ID,
        s3_key=f"{FAKE_TENANT_ID}/{FAKE_AGENT_ID}/{FAKE_DOCUMENT_ID}/doc.pdf",
        file_type="pdf",
        timestamp="2026-04-28T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_process_job_updates_status_to_processing() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    payload = _make_payload()

    with (
        patch(_PATCH_STUB, AsyncMock(side_effect=RuntimeError("stop"))),
        pytest.raises(RuntimeError),
    ):
        await process_job(payload, db, aws_mock, settings)

    mock_docs = db["documents"]
    first_mongo_call = mock_docs.update_one.call_args_list[0]
    assert first_mongo_call[0][1] == {"$set": {"status": "processing"}}

    dynamo_client = aws_mock.client("dynamodb").__aenter__.return_value
    first_dynamo_call = dynamo_client.update_item.call_args_list[0]
    assert first_dynamo_call[1]["ExpressionAttributeValues"][":st"] == {"S": "processing"}


@pytest.mark.asyncio
async def test_process_job_success_updates_status_to_ready() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    payload = _make_payload()

    with patch(_PATCH_STUB, AsyncMock(return_value=None)):
        await process_job(payload, db, aws_mock, settings)

    mock_docs = db["documents"]
    last_mongo_call = mock_docs.update_one.call_args_list[-1]
    assert last_mongo_call[0][1] == {"$set": {"status": "ready"}}
    assert "error_reason" not in last_mongo_call[0][1]["$set"]

    dynamo_client = aws_mock.client("dynamodb").__aenter__.return_value
    last_dynamo_call = dynamo_client.update_item.call_args_list[-1]
    assert last_dynamo_call[1]["ExpressionAttributeValues"][":st"] == {"S": "ready"}
    assert ":er" not in last_dynamo_call[1]["ExpressionAttributeValues"]


@pytest.mark.asyncio
async def test_process_job_permanent_failure_reraises() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    payload = _make_payload()

    with (
        patch(_PATCH_STUB, AsyncMock(side_effect=PermanentIngestionError("corrupt file"))),
        pytest.raises(PermanentIngestionError),
    ):
        await process_job(payload, db, aws_mock, settings)


@pytest.mark.asyncio
async def test_process_job_transient_failure_reraises() -> None:
    db = _make_db()
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    payload = _make_payload()

    with (
        patch(_PATCH_STUB, AsyncMock(side_effect=RuntimeError("connection timeout"))),
        pytest.raises(RuntimeError),
    ):
        await process_job(payload, db, aws_mock, settings)
