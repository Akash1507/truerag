from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.llm.anthropic import AnthropicLLMProvider


async def _text_stream():
    yield "Token "
    yield "stream"


@pytest.mark.asyncio
async def test_stream_generate_yields_tokens_and_records_usage() -> None:
    stream_obj = MagicMock()
    stream_obj.text_stream = _text_stream()
    stream_obj.get_final_message = AsyncMock(
        return_value=SimpleNamespace(usage=SimpleNamespace(input_tokens=9, output_tokens=5))
    )

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=stream_obj)
    stream_cm.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream = MagicMock(return_value=stream_cm)
    mock_client.close = AsyncMock()

    with (
        patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="sk-anthropic")),
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
        patch("app.providers.llm.anthropic.record_llm_usage") as mock_record_usage,
    ):
        provider = AnthropicLLMProvider()
        tokens = [token async for token in provider.stream_generate("prompt", [])]

    assert tokens == ["Token ", "stream"]
    mock_client.messages.stream.assert_called_once()
    mock_record_usage.assert_called_once_with(9, 5)
    mock_client.close.assert_awaited_once()
