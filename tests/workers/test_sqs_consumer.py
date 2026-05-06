import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.interfaces.queue_backend import QueueBackend, QueueMessage
from app.workers.sqs_consumer import _dispatch


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        sqs_ingestion_queue_url="http://localhost/queue",
    )


def _make_body() -> dict[str, object]:
    return {
        "job_id": "job-001",
        "tenant_id": "tenant-123",
        "agent_id": "agent-456",
        "document_id": "doc-789",
        "s3_key": "tenant-123/agent-456/doc-789/doc.pdf",
        "file_type": "pdf",
        "timestamp": "2026-04-28T00:00:00Z",
    }


def _make_queue_message(receive_count: int = 1) -> QueueMessage:
    return QueueMessage(
        message_id="msg-001",
        body=_make_body(),
        receipt_handle="receipt-abc",
        receive_count=receive_count,
    )


def _make_legacy_sqs_message(receive_count: int = 1) -> dict[str, object]:
    return {
        "MessageId": "msg-001",
        "Body": json.dumps(_make_body()),
        "ReceiptHandle": "receipt-abc",
        "Attributes": {"ApproximateReceiveCount": str(receive_count)},
    }


def _make_aws_session() -> MagicMock:
    sqs_client = AsyncMock()
    sqs_client.delete_message = AsyncMock(return_value={})
    sqs_context = MagicMock()
    sqs_context.__aenter__ = AsyncMock(return_value=sqs_client)
    sqs_context.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.client = MagicMock(return_value=sqs_context)
    return session


class _BackendStub(QueueBackend):
    def __init__(self) -> None:
        self.delete_mock = AsyncMock()

    async def send(self, payload: dict[str, object]) -> None:
        _ = payload

    async def receive(
        self,
        max_messages: int = 1,
        wait_seconds: int = 20,
    ) -> list[QueueMessage]:
        _ = (max_messages, wait_seconds)
        return []

    async def delete(self, receipt_handle: str) -> None:
        await self.delete_mock(receipt_handle)


@pytest.mark.asyncio
async def test_dispatch_success_deletes_message_via_backend() -> None:
    backend = _BackendStub()
    aws_session = _make_aws_session()
    with patch("app.workers.sqs_consumer.process_job", AsyncMock(return_value=None)):
        await _dispatch(_make_queue_message(), backend, _make_settings(), aws_session)
    backend.delete_mock.assert_awaited_once_with("receipt-abc")


@pytest.mark.asyncio
async def test_dispatch_transient_first_attempt_does_not_delete() -> None:
    backend = _BackendStub()
    aws_session = _make_aws_session()
    with patch("app.workers.sqs_consumer.process_job", AsyncMock(side_effect=RuntimeError("timeout"))):
        await _dispatch(_make_queue_message(receive_count=1), backend, _make_settings(), aws_session)
    backend.delete_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_transient_third_attempt_marks_failed_and_deletes() -> None:
    backend = _BackendStub()
    aws_session = _make_aws_session()
    with patch("app.workers.sqs_consumer.process_job", AsyncMock(side_effect=RuntimeError("timeout"))), patch(
        "app.workers.sqs_consumer.document_dao.update", AsyncMock()
    ) as update_doc, patch("app.workers.sqs_consumer.ingestion_job_dao.update", AsyncMock()) as update_job:
        await _dispatch(_make_queue_message(receive_count=3), backend, _make_settings(), aws_session)

    update_doc.assert_awaited_once()
    update_job.assert_awaited_once()
    backend.delete_mock.assert_awaited_once_with("receipt-abc")


@pytest.mark.asyncio
async def test_dispatch_permanent_failure_marks_failed_and_deletes() -> None:
    backend = _BackendStub()
    aws_session = _make_aws_session()
    with patch(
        "app.workers.sqs_consumer.process_job",
        AsyncMock(side_effect=PermanentIngestionError("corrupt file")),
    ), patch("app.workers.sqs_consumer.document_dao.update", AsyncMock()) as update_doc, patch(
        "app.workers.sqs_consumer.ingestion_job_dao.update", AsyncMock()
    ) as update_job:
        await _dispatch(_make_queue_message(), backend, _make_settings(), aws_session)

    update_doc.assert_awaited_once()
    update_job.assert_awaited_once()
    backend.delete_mock.assert_awaited_once_with("receipt-abc")


@pytest.mark.asyncio
async def test_dispatch_legacy_dict_message_path_uses_sqs_backend() -> None:
    session = _make_aws_session()
    with patch("app.workers.sqs_consumer.process_job", AsyncMock(return_value=None)):
        await _dispatch(_make_legacy_sqs_message(), session, _make_settings())

    sqs_client = session.client.return_value.__aenter__.return_value
    sqs_client.delete_message.assert_awaited_once()
