from dataclasses import dataclass

import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.db.dao.document_dao import document_dao
from app.db.dao.ingestion_job_dao import ingestion_job_dao
from app.models.document import DocumentStatus
from app.utils.observability import get_logger

logger = get_logger(__name__)


@dataclass
class IngestionJobPayload:
    job_id: str
    tenant_id: str
    agent_id: str
    document_id: str
    s3_key: str
    file_type: str
    timestamp: str


async def process_job(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    await document_dao.update(
        {"document_id": payload.document_id},
        {"status": DocumentStatus.processing},
    )
    await ingestion_job_dao.update({"job_id": payload.job_id}, {"status": "processing"})

    await _run_pipeline_stub(payload, aws_session, settings)

    await document_dao.update(
        {"document_id": payload.document_id},
        {"status": DocumentStatus.ready},
    )
    await ingestion_job_dao.update({"job_id": payload.job_id}, {"status": "ready"})


async def _run_pipeline_stub(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    logger.info(
        "pipeline not yet implemented for Epic 4",
        extra={
            "extra_data": {
                "job_id": payload.job_id,
                "document_id": payload.document_id,
                "tenant_id": payload.tenant_id,
            }
        },
    )
