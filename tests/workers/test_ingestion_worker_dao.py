from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.models.ingestion_job import IngestionJobPayload
from app.workers.ingestion_worker import process_job


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        sqs_ingestion_queue_url="http://localhost/queue",
    )


def _make_payload() -> IngestionJobPayload:
    return IngestionJobPayload(
        job_id="job-001",
        tenant_id="tenant-123",
        agent_id="agent-456",
        document_id="doc-789",
        s3_key="tenant/agent/doc.pdf",
        file_type="pdf",
        timestamp="2026-04-28T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_process_job_updates_processing_then_ready() -> None:
    with patch("app.workers.ingestion_worker.run_ingestion_pipeline", AsyncMock(return_value=None)), patch(
        "app.workers.ingestion_worker.document_dao.update", AsyncMock()
    ) as update_doc, patch("app.workers.ingestion_worker.ingestion_job_dao.update", AsyncMock()) as update_job:
        await process_job(_make_payload(), AsyncMock(), _make_settings())

    assert update_doc.await_count == 2
    assert update_job.await_count == 2
