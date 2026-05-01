from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.models.agent import AgentDocument
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


def _make_agent() -> MagicMock:
    agent = MagicMock(spec=AgentDocument)
    agent.chunking_strategy = "fixed_size"
    agent.chunk_size = 512
    agent.chunk_overlap = 50
    return agent


@pytest.mark.asyncio
async def test_process_job_updates_processing_then_ready() -> None:
    with (
        patch("app.workers.ingestion_worker.agent_dao.find_one", AsyncMock(return_value=_make_agent())),
        patch("app.workers.ingestion_worker.run_ingestion_pipeline", AsyncMock(return_value=None)),
        patch("app.workers.ingestion_worker.document_dao.update", AsyncMock()) as update_doc,
        patch("app.workers.ingestion_worker.ingestion_job_dao.update", AsyncMock()) as update_job,
    ):
        await process_job(_make_payload(), AsyncMock(), _make_settings())

    assert update_doc.await_count == 2
    assert update_job.await_count == 2


@pytest.mark.asyncio
async def test_agent_not_found_marks_failed_and_raises_permanent_error() -> None:
    with (
        patch("app.workers.ingestion_worker.agent_dao.find_one", AsyncMock(return_value=None)),
        patch("app.workers.ingestion_worker.document_dao.update", AsyncMock()) as update_doc,
        patch("app.workers.ingestion_worker.ingestion_job_dao.update", AsyncMock()) as update_job,
    ):
        with pytest.raises(PermanentIngestionError):
            await process_job(_make_payload(), AsyncMock(), _make_settings())

    # processing update + failed update for both doc and job
    assert update_doc.await_count == 2
    assert update_job.await_count == 2

    # Verify failed status was set
    failed_doc_call = update_doc.call_args_list[-1]
    assert failed_doc_call[0][1]["status"] == "failed"
    assert failed_doc_call[0][1]["error_reason"] == "Agent not found — document cannot be retried"

    failed_job_call = update_job.call_args_list[-1]
    assert failed_job_call[0][1]["status"] == "failed"
    assert failed_job_call[0][1]["error_reason"] == "Agent not found — document cannot be retried"
