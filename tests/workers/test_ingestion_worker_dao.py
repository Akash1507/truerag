from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
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
    agent = MagicMock()
    agent.chunking_strategy = "fixed_size"
    agent.chunk_size = 512
    agent.chunk_overlap = 50
    agent.vector_store = "pgvector"
    return agent


@pytest.mark.asyncio
async def test_process_job_updates_processing_then_ready() -> None:
    current_doc = MagicMock(version=1, lineage_id="lineage-1")
    with (
        patch("app.workers.ingestion_worker.agent_dao.find_one", AsyncMock(return_value=_make_agent())),
        patch("app.workers.ingestion_worker.document_dao.find_one", AsyncMock(return_value=current_doc)),
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


@pytest.mark.asyncio
async def test_process_job_archives_predecessor_after_successful_replacement() -> None:
    current_doc = MagicMock(version=2, lineage_id="lineage-1")
    predecessor = MagicMock(document_id="doc-prev")
    mock_store = MagicMock(delete_document=AsyncMock(return_value=None))
    with (
        patch("app.workers.ingestion_worker.agent_dao.find_one", AsyncMock(return_value=_make_agent())),
        patch("app.workers.ingestion_worker.document_dao.find_one", AsyncMock(side_effect=[current_doc, predecessor])),
        patch("app.workers.ingestion_worker.run_ingestion_pipeline", AsyncMock(return_value=None)),
        patch("app.workers.ingestion_worker.get_vector_store", return_value=mock_store),
        patch("app.workers.ingestion_worker.semantic_cache.invalidate", AsyncMock(return_value=None)) as invalidate,
        patch("app.workers.ingestion_worker.document_dao.update", AsyncMock()) as update_doc,
        patch("app.workers.ingestion_worker.ingestion_job_dao.update", AsyncMock()) as update_job,
    ):
        await process_job(_make_payload(), AsyncMock(), _make_settings())

    mock_store.delete_document.assert_awaited_once_with("tenant-123_agent-456", "doc-prev")
    invalidate.assert_awaited_once_with("agent-456")
    assert update_doc.await_count == 3
    assert update_job.await_count == 2


@pytest.mark.asyncio
async def test_cache_invalidation_failure_does_not_fail_successful_replacement() -> None:
    current_doc = MagicMock(version=2, lineage_id="lineage-1")
    predecessor = MagicMock(document_id="doc-prev")
    mock_store = MagicMock(delete_document=AsyncMock(return_value=None))
    with (
        patch("app.workers.ingestion_worker.agent_dao.find_one", AsyncMock(return_value=_make_agent())),
        patch("app.workers.ingestion_worker.document_dao.find_one", AsyncMock(side_effect=[current_doc, predecessor])),
        patch("app.workers.ingestion_worker.run_ingestion_pipeline", AsyncMock(return_value=None)),
        patch("app.workers.ingestion_worker.get_vector_store", return_value=mock_store),
        patch("app.workers.ingestion_worker.semantic_cache.invalidate", AsyncMock(side_effect=RuntimeError("cache down"))),
        patch("app.workers.ingestion_worker.document_dao.update", AsyncMock()) as update_doc,
        patch("app.workers.ingestion_worker.ingestion_job_dao.update", AsyncMock()) as update_job,
    ):
        await process_job(_make_payload(), AsyncMock(), _make_settings())

    assert update_doc.await_count == 3
    assert update_job.await_count == 2
    ready_doc_call = update_doc.call_args_list[-1]
    assert ready_doc_call[0][1]["status"] == "ready"


@pytest.mark.asyncio
async def test_replacement_cleanup_failure_rolls_back_new_vectors_and_marks_failed() -> None:
    current_doc = MagicMock(version=2, lineage_id="lineage-1")
    predecessor = MagicMock(document_id="doc-prev")
    mock_store = MagicMock(
        delete_document=AsyncMock(side_effect=[RuntimeError("delete old failed"), None])
    )
    with (
        patch("app.workers.ingestion_worker.agent_dao.find_one", AsyncMock(return_value=_make_agent())),
        patch("app.workers.ingestion_worker.document_dao.find_one", AsyncMock(side_effect=[current_doc, predecessor])),
        patch("app.workers.ingestion_worker.run_ingestion_pipeline", AsyncMock(return_value=None)),
        patch("app.workers.ingestion_worker.get_vector_store", return_value=mock_store),
        patch("app.workers.ingestion_worker.document_dao.update", AsyncMock()) as update_doc,
        patch("app.workers.ingestion_worker.ingestion_job_dao.update", AsyncMock()) as update_job,
    ):
        with pytest.raises(RuntimeError, match="delete old failed"):
            await process_job(_make_payload(), AsyncMock(), _make_settings())

    assert mock_store.delete_document.await_args_list[0].args == ("tenant-123_agent-456", "doc-prev")
    assert mock_store.delete_document.await_args_list[1].args == ("tenant-123_agent-456", "doc-789")
    failed_doc_call = update_doc.call_args_list[-1]
    failed_job_call = update_job.call_args_list[-1]
    assert failed_doc_call[0][1]["status"] == "failed"
    assert failed_job_call[0][1]["status"] == "failed"


@pytest.mark.asyncio
async def test_replacement_failure_does_not_archive_predecessor() -> None:
    current_doc = MagicMock(version=2, lineage_id="lineage-1")
    with (
        patch("app.workers.ingestion_worker.agent_dao.find_one", AsyncMock(return_value=_make_agent())),
        patch("app.workers.ingestion_worker.document_dao.find_one", AsyncMock(return_value=current_doc)),
        patch("app.workers.ingestion_worker.run_ingestion_pipeline", AsyncMock(side_effect=RuntimeError("boom"))),
        patch("app.workers.ingestion_worker.get_vector_store", MagicMock()) as get_store,
        patch("app.workers.ingestion_worker.document_dao.update", AsyncMock()) as update_doc,
        patch("app.workers.ingestion_worker.ingestion_job_dao.update", AsyncMock()) as update_job,
    ):
        with pytest.raises(RuntimeError):
            await process_job(_make_payload(), AsyncMock(), _make_settings())

    get_store.assert_not_called()
    assert update_doc.await_count == 2
    assert update_job.await_count == 2
