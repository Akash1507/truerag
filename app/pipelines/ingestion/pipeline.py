import time
from datetime import UTC, datetime

import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.models.agent import AgentDocument
from app.models.chunk import Chunk, ChunkMetadata
from app.models.ingestion_job import IngestionJobPayload
from app.pipelines.ingestion.parser import parse_document
from app.providers.registry import CHUNKING_REGISTRY
from app.utils.observability import get_logger
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


async def run_ingestion_pipeline(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
    agent: AgentDocument,
) -> None:
    content = await _download_from_s3(payload, aws_session, settings)
    raw_text = parse_document(content, payload.file_type)
    scrubbed_text = _scrub_with_logging(raw_text, payload)
    chunks = _chunk_text(scrubbed_text, payload, agent)
    await _embed_upsert_stub(chunks, payload)


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


def _chunk_text(
    text: str, payload: IngestionJobPayload, agent: AgentDocument
) -> list[Chunk]:
    chunker_cls = CHUNKING_REGISTRY[agent.chunking_strategy]
    chunker = chunker_cls(chunk_size=agent.chunk_size, chunk_overlap=agent.chunk_overlap)
    metadata = ChunkMetadata(
        tenant_id=payload.tenant_id,
        agent_id=payload.agent_id,
        document_id=payload.document_id,
        chunk_index=0,
        chunking_strategy=agent.chunking_strategy,
        timestamp=datetime.now(UTC),
        version=1,
    )
    chunks = chunker.chunk(text, metadata)
    if not chunks:
        raise PermanentIngestionError("Document produced zero chunks after parsing")
    logger.info(
        "chunking_complete",
        extra={
            "operation": "chunking",
            "extra_data": {
                "tenant_id": payload.tenant_id,
                "agent_id": payload.agent_id,
                "document_id": payload.document_id,
                "chunk_count": len(chunks),
                "chunking_strategy": agent.chunking_strategy,
                "chunk_size": agent.chunk_size,
                "chunk_overlap": agent.chunk_overlap,
            },
        },
    )
    return chunks


async def _embed_upsert_stub(chunks: list[Chunk], payload: IngestionJobPayload) -> None:
    logger.info(
        "embedding_not_yet_implemented",
        extra={
            "extra_data": {
                "tenant_id": payload.tenant_id,
                "agent_id": payload.agent_id,
                "job_id": payload.job_id,
                "document_id": payload.document_id,
                "chunk_count": len(chunks),
            }
        },
    )
