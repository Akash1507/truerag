from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import PermanentIngestionError
from app.models.ingestion_job import IngestionJobPayload
from app.pipelines.ingestion.pipeline import run_ingestion_pipeline


def _settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        sqs_ingestion_queue_url="http://localhost/queue",
        s3_document_bucket="bucket",
    )


def _payload() -> IngestionJobPayload:
    return IngestionJobPayload(
        job_id="job-1",
        tenant_id="tenant-1",
        agent_id="agent-1",
        document_id="doc-1",
        s3_key="tenant-1/agent-1/doc-1/file.txt",
        file_type="txt",
        timestamp="2026-05-16T00:00:00Z",
    )


def _agent_with_unknown_chunker() -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="unknown_strategy",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        query_rewrite=False,
        rerank_pool_size=20,
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        embedding_provider_mismatch=False,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_unknown_chunking_strategy_raises_permanent_ingestion_error() -> None:
    with (
        patch("app.pipelines.ingestion.pipeline.get_file", AsyncMock(return_value=b"hello")),
        patch("app.pipelines.ingestion.pipeline.parse_document", return_value="hello"),
        patch("app.pipelines.ingestion.pipeline.scrub_pii", return_value="hello"),
        pytest.raises(PermanentIngestionError, match="Unknown chunking strategy: unknown_strategy"),
    ):
        await run_ingestion_pipeline(
            payload=_payload(),
            aws_session=AsyncMock(),
            settings=_settings(),
            agent=_agent_with_unknown_chunker(),
        )
