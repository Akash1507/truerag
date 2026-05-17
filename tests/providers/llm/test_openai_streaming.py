from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.llm.openai import OpenAILLMProvider


async def _fake_openai_stream():
    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))], usage=None)
    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))], usage=None)
    yield SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7),
    )


@pytest.mark.asyncio
async def test_stream_generate_yields_tokens_and_records_usage() -> None:
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_fake_openai_stream())
    mock_client.close = AsyncMock()

    with (
        patch("app.providers.llm.openai.get_secret", AsyncMock(return_value="sk-openai")),
        patch("app.providers.llm.openai.AsyncOpenAI", return_value=mock_client),
        patch("app.providers.llm.openai.record_llm_usage") as mock_record_usage,
    ):
        provider = OpenAILLMProvider()
        tokens = [token async for token in provider.stream_generate("prompt", [])]

    assert tokens == ["Hel", "lo"]
    mock_client.chat.completions.create.assert_awaited_once()
    assert mock_client.chat.completions.create.await_args.kwargs["stream"] is True
    assert mock_client.chat.completions.create.await_args.kwargs["stream_options"] == {
        "include_usage": True
    }
    mock_record_usage.assert_called_once_with(12, 7)
    mock_client.close.assert_awaited_once()
