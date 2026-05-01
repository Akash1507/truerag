import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import ParseError, ProviderUnavailableError
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


def _make_chunk() -> Chunk:
    return Chunk(
        text="some text",
        metadata=ChunkMetadata(
            tenant_id="tenant-123",
            agent_id="agent-456",
            document_id="doc-789",
            chunk_index=0,
            chunking_strategy="fixed_size",
            timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
            version=1,
        ),
    )


@pytest.mark.asyncio
async def test_pipeline_calls_scrub_pii_with_extracted_text() -> None:
    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=b"John Smith works here"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.scrub_pii",
            return_value="<PERSON> works here",
        ) as mock_scrub,
        patch(
            "app.pipelines.ingestion.pipeline._chunk_text",
            return_value=[_make_chunk()],
        ),
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ),
    ):
        await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings(), _make_agent())

    mock_scrub.assert_called_once()
    assert mock_scrub.call_args[0][0] == "John Smith works here"


@pytest.mark.asyncio
async def test_scrubbed_text_passed_to_chunk_text() -> None:
    raw = b"Call me at 555-1234"
    scrubbed = "Call me at <PHONE_NUMBER>"

    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=raw),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.scrub_pii",
            return_value=scrubbed,
        ),
        patch(
            "app.pipelines.ingestion.pipeline._chunk_text",
            return_value=[_make_chunk()],
        ) as mock_chunk,
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ),
    ):
        await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings(), _make_agent())

    mock_chunk.assert_called_once()
    assert mock_chunk.call_args[0][0] == scrubbed


@pytest.mark.asyncio
async def test_provider_unavailable_propagates() -> None:
    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=b"some text"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.scrub_pii",
            side_effect=ProviderUnavailableError("Presidio down"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._chunk_text",
            return_value=[],
        ),
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(ProviderUnavailableError):
            await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings(), _make_agent())


@pytest.mark.asyncio
async def test_log_includes_required_fields_and_no_text_content() -> None:
    raw_text = "Alice email: alice@example.com"
    scrubbed_text = "<PERSON> email: <EMAIL_ADDRESS>"

    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=raw_text.encode()),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.scrub_pii",
            return_value=scrubbed_text,
        ),
        patch(
            "app.pipelines.ingestion.pipeline._chunk_text",
            return_value=[_make_chunk()],
        ),
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ),
        patch("app.pipelines.ingestion.pipeline.logger") as mock_logger,
    ):
        payload = _make_payload()
        await run_ingestion_pipeline(payload, AsyncMock(), _make_settings(), _make_agent())

    pii_scrub_calls = [
        c for c in mock_logger.info.call_args_list if c[0][0] == "pii_scrub"
    ]
    assert len(pii_scrub_calls) == 1

    extra_data = pii_scrub_calls[0][1]["extra"]["extra_data"]
    assert extra_data["tenant_id"] == payload.tenant_id
    assert extra_data["agent_id"] == payload.agent_id
    assert extra_data["document_id"] == payload.document_id
    assert "latency_ms" in extra_data

    for log_call in mock_logger.info.call_args_list:
        serialized = json.dumps(
            {"args": list(log_call.args), "kwargs": log_call.kwargs}, default=str
        )
        assert raw_text not in serialized
        assert scrubbed_text not in serialized


@pytest.mark.asyncio
async def test_s3_failure_propagates() -> None:
    s3_error = RuntimeError("NoSuchKey")

    with patch(
        "app.pipelines.ingestion.pipeline._download_from_s3",
        AsyncMock(side_effect=s3_error),
    ):
        with pytest.raises(RuntimeError, match="NoSuchKey"):
            await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings(), _make_agent())


@pytest.mark.asyncio
async def test_pipeline_calls_parse_document() -> None:
    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=b"Hello world"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.parse_document",
            return_value="Hello world",
        ) as mock_parse,
        patch(
            "app.pipelines.ingestion.pipeline.scrub_pii",
            return_value="Hello world",
        ),
        patch(
            "app.pipelines.ingestion.pipeline._chunk_text",
            return_value=[_make_chunk()],
        ),
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ),
    ):
        payload = _make_payload()
        await run_ingestion_pipeline(payload, AsyncMock(), _make_settings(), _make_agent())

    mock_parse.assert_called_once_with(b"Hello world", payload.file_type)


@pytest.mark.asyncio
async def test_pipeline_calls_chunker_via_registry() -> None:
    mock_chunker_cls = MagicMock()
    mock_chunker_instance = MagicMock()
    mock_chunker_instance.chunk.return_value = [_make_chunk()]
    mock_chunker_cls.return_value = mock_chunker_instance

    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=b"some text"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.parse_document",
            return_value="some text",
        ),
        patch(
            "app.pipelines.ingestion.pipeline.scrub_pii",
            return_value="some text",
        ),
        patch(
            "app.pipelines.ingestion.pipeline.CHUNKING_REGISTRY",
            {"fixed_size": mock_chunker_cls},
        ),
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ),
    ):
        await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings(), _make_agent())

    mock_chunker_cls.assert_called_once_with(chunk_size=512, chunk_overlap=50)
    mock_chunker_instance.chunk.assert_called_once()


@pytest.mark.asyncio
async def test_parse_error_propagates() -> None:
    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=b"\xff\xfe bad bytes"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.parse_document",
            side_effect=ParseError("PDF parse failed"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(ParseError):
            await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings(), _make_agent())


@pytest.mark.asyncio
async def test_pipeline_calls_vector_store_upsert_after_embeddings() -> None:
    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=b"Hello world"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.parse_document",
            return_value="Hello world",
        ),
        patch(
            "app.pipelines.ingestion.pipeline.scrub_pii",
            return_value="Hello world",
        ),
        patch(
            "app.pipelines.ingestion.pipeline._chunk_text",
            return_value=[_make_chunk()],
        ),
        patch(
            "app.pipelines.ingestion.pipeline._generate_embeddings",
            AsyncMock(return_value=None),
        ) as mock_embed,
        patch(
            "app.pipelines.ingestion.pipeline._upsert_to_vector_store",
            AsyncMock(return_value=None),
        ) as mock_upsert,
    ):
        await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings(), _make_agent())

    mock_embed.assert_awaited_once()
    mock_upsert.assert_awaited_once()
