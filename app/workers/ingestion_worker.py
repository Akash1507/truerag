import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.db.dao.document_dao import document_dao
from app.db.dao.ingestion_job_dao import ingestion_job_dao
from app.models.document import DocumentStatus
from app.models.ingestion_job import IngestionJobPayload
from app.pipelines.ingestion.pipeline import run_ingestion_pipeline
from app.utils.observability import get_logger

logger = get_logger(__name__)


async def process_job(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    await document_dao.update(
        {"document_id": payload.document_id},
        {"status": DocumentStatus.processing},
    )
    await ingestion_job_dao.update({"job_id": payload.job_id}, {"status": DocumentStatus.processing})

    try:
        await run_ingestion_pipeline(payload, aws_session, settings)
    except Exception as exc:
        error_reason = str(exc)
        await ingestion_job_dao.update(
            {"job_id": payload.job_id},
            {"status": DocumentStatus.failed, "error_reason": error_reason},
        )
        await document_dao.update(
            {"document_id": payload.document_id},
            {"status": DocumentStatus.failed, "error_reason": error_reason},
        )
        raise

    # Update job first (canonical status source in get_document_status)
    await ingestion_job_dao.update({"job_id": payload.job_id}, {"status": DocumentStatus.ready})
    await document_dao.update(
        {"document_id": payload.document_id},
        {"status": DocumentStatus.ready},
    )
