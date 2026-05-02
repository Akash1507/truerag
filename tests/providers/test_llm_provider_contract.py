import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic as anthropic_lib
import openai
import pytest
from botocore.exceptions import ClientError

from app.core.errors import ProviderUnavailableError
from app.models.chunk import Chunk, ChunkMetadata
from app.providers.llm.anthropic import AnthropicLLMProvider
from app.providers.llm.bedrock import BedrockLLMProvider
from app.providers.llm.openai import OpenAILLMProvider


def _chunk() -> Chunk:
    return Chunk(
        text="ctx",
        metadata=ChunkMetadata(
            tenant_id="t1",
            agent_id="a1",
            document_id="d1",
            chunk_index=0,
            chunking_strategy="fixed_size",
            timestamp="2026-01-01T00:00:00Z",
            version=1,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_cls", [AnthropicLLMProvider, OpenAILLMProvider, BedrockLLMProvider])
async def test_llm_provider_contract_generate_non_empty_without_context(
    provider_cls: type[AnthropicLLMProvider] | type[OpenAILLMProvider] | type[BedrockLLMProvider],
) -> None:
    if provider_cls is AnthropicLLMProvider:
        fake_message = MagicMock()
        fake_message.content = [MagicMock(text="ok")]
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=fake_message)
        client.close = AsyncMock()
        with patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="s")), patch(
            "anthropic.AsyncAnthropic", return_value=client
        ):
            provider = provider_cls()
            result = await provider.generate("prompt", [])
            assert isinstance(result, str) and result
        return

    if provider_cls is OpenAILLMProvider:
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="ok"))]
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)
        client.close = AsyncMock()
        with patch("app.providers.llm.openai.get_secret", AsyncMock(return_value="s")), patch(
            "app.providers.llm.openai.AsyncOpenAI", return_value=client
        ):
            provider = provider_cls()
            result = await provider.generate("prompt", [])
            assert isinstance(result, str) and result
        return

    body = AsyncMock()
    body.read = AsyncMock(
        return_value=json.dumps({"content": [{"text": "ok"}]}).encode("utf-8")
    )
    bedrock_client = AsyncMock()
    bedrock_client.invoke_model = AsyncMock(return_value={"body": body})
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=bedrock_client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client = MagicMock(return_value=client_cm)
    provider = provider_cls(aws_session=session)
    result = await provider.generate("prompt", [])
    assert isinstance(result, str) and result


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_cls", [AnthropicLLMProvider, OpenAILLMProvider, BedrockLLMProvider])
async def test_llm_provider_contract_generate_non_empty_with_context(
    provider_cls: type[AnthropicLLMProvider] | type[OpenAILLMProvider] | type[BedrockLLMProvider],
) -> None:
    if provider_cls is AnthropicLLMProvider:
        fake_message = MagicMock()
        fake_message.content = [MagicMock(text="ok")]
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=fake_message)
        client.close = AsyncMock()
        with patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="s")), patch(
            "anthropic.AsyncAnthropic", return_value=client
        ):
            result = await provider_cls().generate("prompt", [_chunk()])
            assert isinstance(result, str) and result
        return

    if provider_cls is OpenAILLMProvider:
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="ok"))]
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)
        client.close = AsyncMock()
        with patch("app.providers.llm.openai.get_secret", AsyncMock(return_value="s")), patch(
            "app.providers.llm.openai.AsyncOpenAI", return_value=client
        ):
            result = await provider_cls().generate("prompt", [_chunk()])
            assert isinstance(result, str) and result
        return

    body = AsyncMock()
    body.read = AsyncMock(
        return_value=json.dumps({"content": [{"text": "ok"}]}).encode("utf-8")
    )
    bedrock_client = AsyncMock()
    bedrock_client.invoke_model = AsyncMock(return_value={"body": body})
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=bedrock_client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client = MagicMock(return_value=client_cm)
    result = await provider_cls(aws_session=session).generate("prompt", [_chunk()])
    assert isinstance(result, str) and result


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_cls", [AnthropicLLMProvider, OpenAILLMProvider, BedrockLLMProvider])
async def test_llm_provider_contract_transient_error_raises_provider_unavailable(
    provider_cls: type[AnthropicLLMProvider] | type[OpenAILLMProvider] | type[BedrockLLMProvider],
) -> None:
    if provider_cls is AnthropicLLMProvider:
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            side_effect=anthropic_lib.RateLimitError(
                message="rate limit",
                response=MagicMock(request=MagicMock(), status_code=429),
                body={},
            )
        )
        client.close = AsyncMock()
        with patch("app.providers.llm.anthropic.get_secret", AsyncMock(return_value="s")), patch(
            "anthropic.AsyncAnthropic", return_value=client
        ), patch("asyncio.sleep", AsyncMock()):
            with pytest.raises(ProviderUnavailableError):
                await provider_cls().generate("prompt", [])
        return

    if provider_cls is OpenAILLMProvider:
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=openai.RateLimitError("rl", response=MagicMock(), body={})
        )
        client.close = AsyncMock()
        with patch("app.providers.llm.openai.get_secret", AsyncMock(return_value="s")), patch(
            "app.providers.llm.openai.AsyncOpenAI", return_value=client
        ), patch("asyncio.sleep", AsyncMock()):
            with pytest.raises(ProviderUnavailableError):
                await provider_cls().generate("prompt", [])
        return

    client_error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "throttled"}},
        "InvokeModel",
    )
    bedrock_client = AsyncMock()
    bedrock_client.invoke_model = AsyncMock(side_effect=client_error)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=bedrock_client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client = MagicMock(return_value=client_cm)
    with patch("asyncio.sleep", AsyncMock()):
        with pytest.raises(ProviderUnavailableError):
            await provider_cls(aws_session=session).generate("prompt", [])


@pytest.mark.asyncio
async def test_openai_llm_calls_chat_completions() -> None:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="ok"))]
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    client.close = AsyncMock()

    with patch("app.providers.llm.openai.get_secret", AsyncMock(return_value="s")), patch(
        "app.providers.llm.openai.AsyncOpenAI", return_value=client
    ):
        provider = OpenAILLMProvider()
        await provider.generate("hello", [])

    kwargs = client.chat.completions.create.await_args.kwargs
    assert kwargs["model"] == provider.settings.openai_llm_model
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][1]["role"] == "user"


@pytest.mark.asyncio
async def test_bedrock_llm_calls_invoke_model() -> None:
    body = AsyncMock()
    body.read = AsyncMock(return_value=json.dumps({"content": [{"text": "ok"}]}).encode("utf-8"))
    bedrock_client = AsyncMock()
    bedrock_client.invoke_model = AsyncMock(return_value={"body": body})
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=bedrock_client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client = MagicMock(return_value=client_cm)

    provider = BedrockLLMProvider(aws_session=session)
    await provider.generate("hello", [])

    kwargs = bedrock_client.invoke_model.await_args.kwargs
    assert kwargs["modelId"] == provider.settings.bedrock_llm_model_id
    payload = json.loads(kwargs["body"])
    assert payload["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_openai_llm_retries_on_rate_limit() -> None:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="ok"))]
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[openai.RateLimitError("rl", response=MagicMock(), body={}), response]
    )
    client.close = AsyncMock()

    with patch("app.providers.llm.openai.get_secret", AsyncMock(return_value="s")), patch(
        "app.providers.llm.openai.AsyncOpenAI", return_value=client
    ), patch("asyncio.sleep", AsyncMock()):
        result = await OpenAILLMProvider().generate("hello", [])

    assert result == "ok"
    assert client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_bedrock_llm_wraps_client_error() -> None:
    client_error = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "bad request"}},
        "InvokeModel",
    )
    bedrock_client = AsyncMock()
    bedrock_client.invoke_model = AsyncMock(side_effect=client_error)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=bedrock_client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client = MagicMock(return_value=client_cm)

    with pytest.raises(ProviderUnavailableError, match="Bedrock API error"):
        await BedrockLLMProvider(aws_session=session).generate("hello", [])
