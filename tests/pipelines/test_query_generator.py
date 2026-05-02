from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import ProviderUnavailableError
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.generator import generate_answer


def _make_vector_result() -> VectorResult:
    return VectorResult(
        id="doc-1_0",
        score=0.92,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id="doc-1",
            chunk_index=0,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text="chunk one",
    )


@pytest.mark.asyncio
async def test_generate_answer_validates_json_output() -> None:
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(return_value='{"answer":"ok"}')
    mock_provider_cls = MagicMock(return_value=mock_provider)

    with patch("app.pipelines.query.generator.LLM_REGISTRY", {"anthropic": mock_provider_cls}):
        answer = await generate_answer("my query", [_make_vector_result()], "anthropic", output_format="json")

    assert answer == '{"answer": "ok"}'


@pytest.mark.asyncio
async def test_generate_answer_raises_when_json_output_invalid() -> None:
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(return_value="not-json")
    mock_provider_cls = MagicMock(return_value=mock_provider)

    with patch("app.pipelines.query.generator.LLM_REGISTRY", {"anthropic": mock_provider_cls}), pytest.raises(
        ProviderUnavailableError,
        match="invalid JSON output",
    ):
        await generate_answer("my query", [_make_vector_result()], "anthropic", output_format="json")
