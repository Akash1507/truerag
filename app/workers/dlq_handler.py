from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.dao.document_dao import DocumentDAO, document_dao
from app.db.dao.ingestion_job_dao import IngestionJobDAO, ingestion_job_dao
from app.interfaces.queue_backend import QueueBackend
from app.utils.observability import get_logger

logger = get_logger(__name__)


async def run_dlq_sweep(
    queue: QueueBackend,
    job_dao: IngestionJobDAO = ingestion_job_dao,
    document_dao_dep: DocumentDAO = document_dao,
) -> dict[str, int | str]:
    settings = get_settings()
    failed_jobs = await job_dao.get_retriable_failed(max_retries=settings.max_dlq_retries)

    requeued = 0
    exhausted = 0
    permanent = 0
    for job in failed_jobs:
        if job.error_type == "PermanentIngestionError":
            permanent += 1
            continue
        if job.retry_count >= settings.max_dlq_retries:
            exhausted += 1
            continue

        document = await document_dao_dep.find_one({"document_id": job.document_id})
        if document is None:
            exhausted += 1
            continue

        await queue.send(
            {
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "agent_id": document.agent_id,
                "document_id": document.document_id,
                "s3_key": document.s3_key,
                "file_type": document.file_type,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        await job_dao.increment_retry_count(job.job_id)
        requeued += 1

    summary: dict[str, int | str] = {
        "requeued": requeued,
        "exhausted": exhausted,
        "permanent_failures": permanent,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    logger.info("dlq_sweep", extra=summary)
    return summary
