from unittest.mock import AsyncMock, MagicMock, patch

import anthropic as anthropic_lib
import pytest

from app.core.errors import ProviderUnavailableError
from app.providers.llm.anthropic import AnthropicLLMProvider


@pytest.mark.asyncio
async def test_generate_returns_answer() -> None:
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text="The answer is 42.")]
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=fake_message)
    mock_client.close = AsyncMock()

    with (
        patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="sk-ant-test")),
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        provider = AnthropicLLMProvider()
        result = await provider.generate("What is 6*7?", [])

    assert result == "The answer is 42."


@pytest.mark.asyncio
async def test_generate_retry_exhaustion_raises_provider_unavailable() -> None:
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic_lib.RateLimitError(
            message="rate limit",
            response=MagicMock(request=MagicMock(), status_code=429),
            body={},
        )
    )
    mock_client.close = AsyncMock()

    with (
        patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="sk-ant-test")),
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
        patch("asyncio.sleep", AsyncMock()),
    ):
        provider = AnthropicLLMProvider()
        with pytest.raises(ProviderUnavailableError, match="exhausted retries"):
            await provider.generate("query", [])


@pytest.mark.asyncio
async def test_generate_preserves_json_mode_prompt() -> None:
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text='{"answer":"ok"}')]
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=fake_message)
    mock_client.close = AsyncMock()
    prompt = 'Return ONLY JSON: {"answer":"ok"}'

    with (
        patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="sk-ant-test")),
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        provider = AnthropicLLMProvider()
        await provider.generate(prompt, [])

    assert mock_client.messages.create.await_args.kwargs["messages"][0]["content"] == prompt
    assert "Return ONLY a valid JSON object" in mock_client.messages.create.await_args.kwargs["system"]
    assert "No prose, no markdown." in mock_client.messages.create.await_args.kwargs["system"]


@pytest.mark.asyncio
async def test_generate_raises_when_anthropic_returns_no_text_content() -> None:
    fake_message = MagicMock()
    fake_message.content = [MagicMock(input={"type": "tool_use"})]
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=fake_message)
    mock_client.close = AsyncMock()

    with (
        patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="sk-ant-test")),
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        provider = AnthropicLLMProvider()
        with pytest.raises(ProviderUnavailableError, match="returned no text content"):
            await provider.generate("query", [])
