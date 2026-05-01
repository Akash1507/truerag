import time

import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.models.ingestion_job import IngestionJobPayload
from app.utils.observability import get_logger
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


async def run_ingestion_pipeline(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    content = await _download_from_s3(payload, aws_session, settings)
    raw_text = _extract_text(content, payload.file_type)
    scrubbed_text = _scrub_with_logging(raw_text, payload)
    await _chunk_embed_upsert_stub(scrubbed_text, payload)


async def _download_from_s3(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> bytes:
    async with aws_session.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as s3:
        response = await s3.get_object(Bucket=settings.s3_document_bucket, Key=payload.s3_key)
        return await response["Body"].read()


def _extract_text(content: bytes, file_type: str) -> str:
    # txt/md: exact UTF-8; pdf/docx: best-effort stub (Epic 4 replaces with real parsers)
    return content.decode("utf-8", errors="replace")


def _scrub_with_logging(raw_text: str, payload: IngestionJobPayload) -> str:
    t0 = time.perf_counter()
    scrubbed = scrub_pii(raw_text, document_id=payload.document_id)
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "pii_scrub",
        extra={
            "operation": "pii_scrub",
            "extra_data": {
                "tenant_id": payload.tenant_id,
                "agent_id": payload.agent_id,
                "document_id": payload.document_id,
                "latency_ms": latency_ms,
            },
        },
    )
    return scrubbed


async def _chunk_embed_upsert_stub(scrubbed_text: str, payload: IngestionJobPayload) -> None:
    logger.info(
        "chunking_not_yet_implemented",
        extra={
            "extra_data": {
                "job_id": payload.job_id,
                "document_id": payload.document_id,
                "tenant_id": payload.tenant_id,
            }
        },
    )
