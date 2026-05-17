from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.models.ingestion_job import IngestionJobPayload
from app.workers.ingestion_worker import process_job


def _settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        sqs_ingestion_queue_url="http://localhost/queue",
        s3_document_bucket="bucket",
    )


def _payload() -> IngestionJobPayload:
    return IngestionJobPayload(
        job_id="job-1",
        tenant_id="tenant-1",
        agent_id="agent-1",
        document_id="doc-1",
        s3_key="tenant-1/agent-1/doc-1/file.pdf",
        file_type="pdf",
        timestamp="2026-05-16T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_process_job_exits_when_set_processing_fails() -> None:
    with (
        patch("app.workers.ingestion_worker.ingestion_job_dao.set_processing", AsyncMock(return_value=False)) as set_processing,
        patch("app.workers.ingestion_worker.run_ingestion_pipeline", AsyncMock()) as run_pipeline,
        patch("app.workers.ingestion_worker.document_dao.update", AsyncMock()) as update_doc,
    ):
        await process_job(_payload(), AsyncMock(), _settings())

    set_processing.assert_awaited_once_with("job-1")
    run_pipeline.assert_not_awaited()
    update_doc.assert_not_awaited()
