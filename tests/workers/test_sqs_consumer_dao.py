import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.workers.sqs_consumer import _dispatch


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        sqs_ingestion_queue_url="http://localhost/queue",
    )


def _make_aws_mock() -> MagicMock:
    sqs = AsyncMock()
    sqs.delete_message = AsyncMock(return_value={})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=sqs)
    cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client = MagicMock(return_value=cm)
    return session


def _make_message(receive_count: int = 1) -> dict[str, object]:
    return {
        "Body": json.dumps(
            {
                "job_id": "job-001",
                "tenant_id": "tenant-123",
                "agent_id": "agent-456",
                "document_id": "doc-789",
                "s3_key": "tenant/agent/doc.pdf",
                "file_type": "pdf",
                "timestamp": "2026-04-28T00:00:00Z",
            }
        ),
        "ReceiptHandle": "receipt-handle-abc",
        "Attributes": {"ApproximateReceiveCount": str(receive_count)},
    }


@pytest.mark.asyncio
async def test_dispatch_success_deletes_message() -> None:
    aws = _make_aws_mock()
    with patch("app.workers.sqs_consumer.process_job", AsyncMock(return_value=None)):
        await _dispatch(_make_message(), aws, _make_settings())

    aws.client.return_value.__aenter__.return_value.delete_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_permanent_failure_updates_status_and_deletes() -> None:
    aws = _make_aws_mock()
    with patch(
        "app.workers.sqs_consumer.process_job",
        AsyncMock(side_effect=PermanentIngestionError("corrupt file")),
    ), patch("app.workers.sqs_consumer.document_dao.update", AsyncMock()) as update_doc, patch(
        "app.workers.sqs_consumer.ingestion_job_dao.update", AsyncMock()
    ) as update_job:
        await _dispatch(_make_message(), aws, _make_settings())

    update_doc.assert_awaited_once()
    update_job.assert_awaited_once()
