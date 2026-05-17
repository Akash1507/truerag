import hashlib
from datetime import UTC, datetime

import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.dependencies import get_vector_store
from app.core.errors import CircuitOpenError, PermanentIngestionError, ServiceUnavailableError
from app.models.agent import AgentDocument
from app.models.chunk import Chunk, ChunkMetadata, VectorRecord
from app.models.ingestion_job import IngestionJobPayload
from app.pipelines.ingestion.parser import parse_document
from app.providers.registry import CHUNKING_REGISTRY, EMBEDDING_REGISTRY
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.file_store import get_file
from app.utils.observability import (
    LatencyTracker,
    get_logger,
    log_stage_latency,
    reset_request_context,
    set_request_context,
)
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


class _IngestionPipelineCircuitBreakers:
    def __init__(self) -> None:
        self._cb_embed = CircuitBreaker()
        self._cb_vector = CircuitBreaker()


async def run_ingestion_pipeline(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
    agent: AgentDocument,
    document_version: int = 1,
) -> None:
    tokens = set_request_context(
        request_id=payload.job_id,
        tenant_id=payload.tenant_id,
        agent_id=payload.agent_id,
    )
    breakers = _IngestionPipelineCircuitBreakers()
    try:
        content = await get_file(payload.s3_key, settings, aws_session)

        tracker = LatencyTracker()
        raw_text = parse_document(content, payload.file_type)
        log_stage_latency(logger, "parse", tracker.elapsed_ms())

        scrubbed_text = _scrub_with_logging(raw_text, payload)

        tracker = LatencyTracker()
        chunks = _chunk_text(scrubbed_text, payload, agent, document_version)
        log_stage_latency(logger, "chunk", tracker.elapsed_ms())

        tracker = LatencyTracker()
        chunks_to_embed = await _deduplicate_chunks(chunks, payload, agent)
        log_stage_latency(logger, "dedup", tracker.elapsed_ms())

        tracker = LatencyTracker()
        await _generate_embeddings(chunks_to_embed, agent, aws_session, breakers)
        log_stage_latency(logger, "embed", tracker.elapsed_ms())

        tracker = LatencyTracker()
        await _upsert_to_vector_store(chunks_to_embed, payload, agent, breakers)
        log_stage_latency(logger, "upsert", tracker.elapsed_ms())
    except CircuitOpenError as exc:
        raise ServiceUnavailableError("Provider circuit is open") from exc
    finally:
        reset_request_context(tokens)


def _scrub_with_logging(raw_text: str, payload: IngestionJobPayload) -> str:
    tracker = LatencyTracker()
    scrubbed = scrub_pii(raw_text, document_id=payload.document_id)
    latency_ms = tracker.elapsed_ms()
    logger.info(
        "pii_scrub",
        extra={
            "operation": "pii_scrub",
            "latency_ms": latency_ms,
            "extra_data": {
                "tenant_id": payload.tenant_id,
                "agent_id": payload.agent_id,
                "document_id": payload.document_id,
            },
        },
    )
    return scrubbed


def _chunk_text(
    text: str, payload: IngestionJobPayload, agent: AgentDocument, document_version: int
) -> list[Chunk]:
    chunker_cls = CHUNKING_REGISTRY.get(agent.chunking_strategy)
    if not chunker_cls:
        raise PermanentIngestionError(f"Unknown chunking strategy: {agent.chunking_strategy}")
    chunker = chunker_cls(chunk_size=agent.chunk_size, chunk_overlap=agent.chunk_overlap)
    metadata = ChunkMetadata(
        tenant_id=payload.tenant_id,
        agent_id=payload.agent_id,
        document_id=payload.document_id,
        chunk_index=0,
        chunking_strategy=agent.chunking_strategy,
        timestamp=datetime.now(UTC),
        version=document_version,
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
    chunks: list[Chunk],
    agent: AgentDocument,
    aws_session: aioboto3.Session,
    breakers: _IngestionPipelineCircuitBreakers,
) -> None:
    if not chunks:
        return

    embedder_cls = EMBEDDING_REGISTRY.get(agent.embedding_provider)
    if not embedder_cls:
        raise ValueError(f"Embedding provider '{agent.embedding_provider}' is not registered.")
    embedder = embedder_cls(aws_session=aws_session)

    texts = [c.text for c in chunks]
    vectors: list[list[float]] = []

    batch_size = 2000
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        batch_vectors = await breakers._cb_embed.call(embedder.embed, batch_texts)
        vectors.extend(batch_vectors)

    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.vector = vector

    logger.info(
        "embedding_complete",
        extra={
            "operation": "embedding",
            "extra_data": {
                "tenant_id": chunks[0].metadata.tenant_id,
                "agent_id": agent.id,
                "provider": agent.embedding_provider,
                "chunk_count": len(chunks),
                "vector_dim": len(vectors[0]) if vectors else 0,
            },
        },
    )


async def _deduplicate_chunks(
    chunks: list[Chunk], payload: IngestionJobPayload, agent: AgentDocument
) -> list[Chunk]:
    namespace = f"{payload.tenant_id}_{payload.agent_id}"
    vector_store = get_vector_store(agent.vector_store)
    existing_hashes = await vector_store.list_hashes(namespace)

    chunks_to_embed: list[Chunk] = []
    skipped_count = 0
    for chunk in chunks:
        content_hash = hashlib.sha256(chunk.text.encode()).hexdigest()[:16]
        chunk.metadata.content_hash = content_hash
        if content_hash in existing_hashes:
            skipped_count += 1
            continue
        existing_hashes.add(content_hash)
        chunks_to_embed.append(chunk)

    logger.info(
        "chunks_deduplicated",
        extra={
            "operation": "chunk_deduplication",
            "extra_data": {
                "tenant_id": payload.tenant_id,
                "agent_id": payload.agent_id,
                "document_id": payload.document_id,
                "skipped_count": skipped_count,
                "upserted_count": len(chunks_to_embed),
            },
        },
    )
    return chunks_to_embed


async def _upsert_to_vector_store(
    chunks: list[Chunk],
    payload: IngestionJobPayload,
    agent: AgentDocument,
    breakers: _IngestionPipelineCircuitBreakers,
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

    await breakers._cb_vector.call(vector_store.upsert, namespace=namespace, vectors=vector_records)
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
