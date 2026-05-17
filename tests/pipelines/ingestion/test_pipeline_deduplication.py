import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.models.agent import AgentDocument
from app.models.chunk import Chunk, ChunkMetadata
from app.models.ingestion_job import IngestionJobPayload
from app.pipelines.ingestion.pipeline import run_ingestion_pipeline


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
        s3_key="tenant/agent/doc.txt",
        file_type="txt",
        timestamp="2026-05-01T00:00:00Z",
    )


def _make_agent() -> AgentDocument:
    agent = MagicMock(spec=AgentDocument)
    agent.chunking_strategy = "fixed_size"
    agent.chunk_size = 512
    agent.chunk_overlap = 50
    agent.vector_store = "pgvector"
    agent.embedding_provider = "openai"
    agent.id = "agent-456"
    agent.tenant_id = "tenant-123"
    agent.agent_id = "agent-456"
    return agent


def _make_chunk(text: str, chunk_index: int) -> Chunk:
    return Chunk(
        text=text,
        metadata=ChunkMetadata(
            tenant_id="tenant-123",
            agent_id="agent-456",
            document_id="doc-789",
            chunk_index=chunk_index,
            chunking_strategy="fixed_size",
            timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
            version=1,
        ),
    )


@pytest.mark.asyncio
async def test_pipeline_deduplicates_chunks_per_namespace_before_embedding() -> None:
    existing_text = "existing chunk"
    new_text = "new chunk"
    existing_hash = hashlib.sha256(existing_text.encode()).hexdigest()[:16]

    existing_chunk = _make_chunk(existing_text, 0)
    new_chunk = _make_chunk(new_text, 1)
    vector_store = MagicMock()
    vector_store.list_hashes = AsyncMock(return_value={existing_hash})

    with (
        patch("app.pipelines.ingestion.pipeline.get_file", AsyncMock(return_value=b"input")),
        patch("app.pipelines.ingestion.pipeline.parse_document", return_value="parsed"),
        patch("app.pipelines.ingestion.pipeline.scrub_pii", return_value="parsed"),
        patch(
            "app.pipelines.ingestion.pipeline._chunk_text",
            return_value=[existing_chunk, new_chunk],
        ),
        patch("app.pipelines.ingestion.pipeline.get_vector_store", return_value=vector_store),
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ) as mock_embed,
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ) as mock_upsert,
        patch("app.pipelines.ingestion.pipeline.logger") as mock_logger,
    ):
        await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings(), _make_agent())

    vector_store.list_hashes.assert_awaited_once_with("tenant-123_agent-456")

    embed_chunks = mock_embed.await_args.args[0]
    upsert_chunks = mock_upsert.await_args.args[0]
    assert [chunk.text for chunk in embed_chunks] == [new_text]
    assert [chunk.text for chunk in upsert_chunks] == [new_text]

    assert existing_chunk.metadata.content_hash == existing_hash
    assert new_chunk.metadata.content_hash == hashlib.sha256(new_text.encode()).hexdigest()[:16]

    dedup_logs = [
        call for call in mock_logger.info.call_args_list if call.args and call.args[0] == "chunks_deduplicated"
    ]
    assert len(dedup_logs) == 1
    assert dedup_logs[0].kwargs["extra"]["extra_data"]["skipped_count"] == 1
    assert dedup_logs[0].kwargs["extra"]["extra_data"]["upserted_count"] == 1
