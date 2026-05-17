from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.faithfulness_check import check_hallucination


def _make_agent() -> AgentDocument:
    return AgentDocument.model_construct(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        rerank_pool_size=20,
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        embedding_provider_mismatch=False,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_result(text: str = "chunk text") -> VectorResult:
    return VectorResult(
        id="doc-1_0",
        score=0.9,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id="doc-1",
            chunk_index=0,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text=text,
    )


@pytest.mark.asyncio
async def test_check_hallucination_low_when_supported_high_confidence() -> None:
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(
        return_value='{"supported": true, "confidence": 0.92, "unsupported_claims": []}'
    )
    mock_provider_cls = MagicMock(return_value=mock_provider)

    with patch(
        "app.pipelines.query.faithfulness_check.LLM_REGISTRY",
        {"anthropic": mock_provider_cls},
    ):
        risk = await check_hallucination("answer", [_make_result()], _make_agent())

    assert risk == "low"


@pytest.mark.asyncio
async def test_check_hallucination_medium_when_supported_lower_confidence() -> None:
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(return_value='{"supported": true, "confidence": 0.70}')
    mock_provider_cls = MagicMock(return_value=mock_provider)

    with patch(
        "app.pipelines.query.faithfulness_check.LLM_REGISTRY",
        {"anthropic": mock_provider_cls},
    ):
        risk = await check_hallucination("answer", [_make_result()], _make_agent())

    assert risk == "medium"


@pytest.mark.asyncio
async def test_check_hallucination_high_when_unsupported() -> None:
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(return_value='{"supported": false, "confidence": 0.3}')
    mock_provider_cls = MagicMock(return_value=mock_provider)

    with patch(
        "app.pipelines.query.faithfulness_check.LLM_REGISTRY",
        {"anthropic": mock_provider_cls},
    ):
        risk = await check_hallucination("answer", [_make_result()], _make_agent())

    assert risk == "high"


@pytest.mark.asyncio
async def test_check_hallucination_returns_none_on_provider_exception() -> None:
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(side_effect=RuntimeError("judge failed"))
    mock_provider_cls = MagicMock(return_value=mock_provider)

    with patch(
        "app.pipelines.query.faithfulness_check.LLM_REGISTRY",
        {"anthropic": mock_provider_cls},
    ):
        risk = await check_hallucination("answer", [_make_result()], _make_agent())

    assert risk is None


@pytest.mark.asyncio
async def test_check_hallucination_uses_inner_answer_for_json_envelope() -> None:
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(return_value='{"supported": true, "confidence": 0.92}')
    mock_provider_cls = MagicMock(return_value=mock_provider)

    with patch(
        "app.pipelines.query.faithfulness_check.LLM_REGISTRY",
        {"anthropic": mock_provider_cls},
    ):
        await check_hallucination('{"answer":"inner answer"}', [_make_result()], _make_agent())

    prompt = mock_provider.generate.await_args.args[0]
    assert "ANSWER:\ninner answer" in prompt
