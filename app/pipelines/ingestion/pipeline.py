import time
from datetime import UTC, datetime

import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.models.agent import AgentDocument
from app.core.dependencies import get_vector_store
from app.models.chunk import Chunk, ChunkMetadata, VectorRecord
from app.models.ingestion_job import IngestionJobPayload
from app.pipelines.ingestion.parser import parse_document
from app.providers.registry import CHUNKING_REGISTRY, EMBEDDING_REGISTRY
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
    await _generate_embeddings(chunks, agent, aws_session)
    await _upsert_to_vector_store(chunks, payload, agent)


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
    chunker_cls = CHUNKING_REGISTRY.get(agent.chunking_strategy)
    if not chunker_cls:
        raise ValueError(f"Chunking strategy '{agent.chunking_strategy}' is not registered.")
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


async def _generate_embeddings(
    chunks: list[Chunk], agent: AgentDocument, aws_session: aioboto3.Session
) -> None:
    embedder_cls = EMBEDDING_REGISTRY.get(agent.embedding_provider)
    if not embedder_cls:
        raise ValueError(f"Embedding provider '{agent.embedding_provider}' is not registered.")
    embedder = embedder_cls(aws_session=aws_session)

    texts = [c.text for c in chunks]
    vectors = []
    
    batch_size = 2000
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        batch_vectors = await embedder.embed(batch_texts)
        vectors.extend(batch_vectors)

    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.vector = vector

    logger.info(
        "embedding_complete",
        extra={
            "operation": "embedding",
            "extra_data": {
                "tenant_id": chunks[0].metadata.tenant_id if chunks else None,
                "agent_id": agent.id,
                "provider": agent.embedding_provider,
                "chunk_count": len(chunks),
                "vector_dim": len(vectors[0]) if vectors else 0,
            },
        },
    )


async def _upsert_to_vector_store(
    chunks: list[Chunk], payload: IngestionJobPayload, agent: AgentDocument
) -> None:
    namespace = f"{payload.tenant_id}_{payload.agent_id}"
    vector_store = get_vector_store(agent.vector_store)
    vector_records: list[VectorRecord] = []
    for chunk in chunks:
        if chunk.vector is None:
            raise PermanentIngestionError(
                f"Missing embedding vector for chunk {chunk.metadata.chunk_index}"
            )
        vector_records.append(
            VectorRecord(
                id=f"{chunk.metadata.document_id}_{chunk.metadata.chunk_index}",
                vector=chunk.vector,
                metadata=chunk.metadata,
                text=chunk.text,
            )
        )
    await vector_store.upsert(namespace=namespace, vectors=vector_records)
    logger.info(
        "vector_upsert_complete",
        extra={
            "operation": "vector_upsert",
            "extra_data": {
                "tenant_id": payload.tenant_id,
                "agent_id": payload.agent_id,
                "job_id": payload.job_id,
                "document_id": payload.document_id,
                "chunk_count": len(chunks),
                "vector_dim": len(chunks[0].vector) if chunks and chunks[0].vector else 0,
                "provider": agent.vector_store,
            }
        },
    )
