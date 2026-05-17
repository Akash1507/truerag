from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chunk import ChunkMetadata, VectorResult
from app.models.conversation import ConversationMessage
from app.pipelines.query.generator import generate_answer


def _result(text: str) -> VectorResult:
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
async def test_generate_answer_prepends_conversation_history() -> None:
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value="ok")
    provider_cls = MagicMock(return_value=provider)
    history = [
        ConversationMessage(role="user", content="First question", timestamp=datetime.now(UTC)),
        ConversationMessage(role="assistant", content="First answer", timestamp=datetime.now(UTC)),
    ]

    with patch("app.pipelines.query.generator.LLM_REGISTRY", {"anthropic": provider_cls}):
        await generate_answer(
            query="follow up",
            results=[_result("context chunk")],
            llm_provider_name="anthropic",
            conversation_history=history,
            context_window_tokens=8192,
        )

    prompt = provider.generate.await_args.args[0]
    assert "This is a continuation of a previous conversation." in prompt
    assert "User: First question" in prompt
    assert "Assistant: First answer" in prompt
    assert "Question: follow up" in prompt


@pytest.mark.asyncio
async def test_generate_answer_trims_old_history_to_fit_context_window() -> None:
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value="ok")
    provider_cls = MagicMock(return_value=provider)
    history = [
        ConversationMessage(role="user", content="old one old one old one", timestamp=datetime.now(UTC)),
        ConversationMessage(role="assistant", content="old two old two old two", timestamp=datetime.now(UTC)),
        ConversationMessage(role="user", content="new one", timestamp=datetime.now(UTC)),
        ConversationMessage(role="assistant", content="new two", timestamp=datetime.now(UTC)),
    ]

    with patch("app.pipelines.query.generator.LLM_REGISTRY", {"anthropic": provider_cls}):
        await generate_answer(
            query="follow up",
            results=[_result("context chunk")],
            llm_provider_name="anthropic",
            conversation_history=history,
            context_window_tokens=30,
        )

    prompt = provider.generate.await_args.args[0]
    assert "old one old one old one" not in prompt
    assert "old two old two old two" not in prompt
    assert "This is a continuation of a previous conversation." in prompt
    assert "Question: follow up" in prompt
