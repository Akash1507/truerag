from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.workers.dlq_handler import run_dlq_sweep


@pytest.mark.asyncio
async def test_dlq_sweep_requeues_only_retriable_and_counts_summary() -> None:
    retriable = SimpleNamespace(
        job_id="job-retry",
        document_id="doc-retry",
        tenant_id="tenant-1",
        retry_count=1,
        error_type="TimeoutError",
    )
    exhausted = SimpleNamespace(
        job_id="job-exhausted",
        document_id="doc-exhausted",
        tenant_id="tenant-1",
        retry_count=3,
        error_type="TimeoutError",
    )
    permanent = SimpleNamespace(
        job_id="job-permanent",
        document_id="doc-permanent",
        tenant_id="tenant-1",
        retry_count=0,
        error_type="PermanentIngestionError",
    )

    queue = AsyncMock()
    job_dao = AsyncMock()
    job_dao.get_retriable_failed = AsyncMock(return_value=[retriable, exhausted, permanent])
    doc_dao = AsyncMock()
    doc_dao.find_one = AsyncMock(
        return_value=SimpleNamespace(
            document_id="doc-retry",
            agent_id="agent-1",
            s3_key="tenant-1/agent-1/doc-retry/file.pdf",
            file_type="pdf",
        )
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "app.workers.dlq_handler.get_settings",
            lambda: Settings(max_dlq_retries=3),
        )
        summary = await run_dlq_sweep(queue=queue, job_dao=job_dao, document_dao_dep=doc_dao)

    assert summary["requeued"] == 1
    assert summary["exhausted"] == 1
    assert summary["permanent_failures"] == 1
    assert isinstance(summary["timestamp"], str)

    queue.send.assert_awaited_once()
    job_dao.increment_retry_count.assert_awaited_once_with("job-retry")
