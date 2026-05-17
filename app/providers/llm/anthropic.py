import aioboto3
import anthropic
from collections.abc import AsyncGenerator

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.interfaces.llm_provider import LLMProvider
from app.models.chunk import Chunk
from app.utils.cost_tracker import record_llm_usage
from app.utils.retry import retry
from app.utils.secrets import get_secret

_TRANSIENT_ERRORS = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
)
_BASE_SYSTEM_MESSAGE = "You are a helpful assistant. Answer using only the provided context."
_JSON_OUTPUT_TRIGGERS = (
    'Return ONLY a valid JSON object with a single key "answer"',
    "Return ONLY JSON",
)
_JSON_OUTPUT_SYSTEM_SUFFIX = (
    ' Return ONLY a valid JSON object with a single key "answer" containing your response. '
    "No prose, no markdown."
)
_MODEL = "claude-haiku-4-5-20251001"


class AnthropicLLMProvider(LLMProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session
        self.settings = get_settings()

    @retry(max_attempts=3, backoff_factor=2, retry_on=_TRANSIENT_ERRORS)
    async def _generate_with_retry(
        self,
        client: anthropic.AsyncAnthropic,
        prompt: str,
        system: str,
    ) -> str:
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                usage = getattr(message, "usage", None)
                prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                record_llm_usage(prompt_tokens, completion_tokens)
                return text
        raise ProviderUnavailableError("Anthropic API returned no text content")

    async def generate(self, prompt: str, context: list[Chunk]) -> str:
        _ = context
        api_key = await get_secret(
            self.settings.anthropic_api_key_secret_name,
            session=self.aws_session,
        )
        client = anthropic.AsyncAnthropic(api_key=api_key)
        system = _BASE_SYSTEM_MESSAGE
        if any(trigger in prompt for trigger in _JSON_OUTPUT_TRIGGERS):
            system += _JSON_OUTPUT_SYSTEM_SUFFIX
        try:
            return await self._generate_with_retry(client, prompt, system)
        except ProviderUnavailableError:
            raise
        except _TRANSIENT_ERRORS as exc:
            raise ProviderUnavailableError(f"Anthropic API exhausted retries: {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Anthropic API error: {exc}") from exc
        finally:
            await client.close()

    async def stream_generate(
        self,
        prompt: str,
        context: list[Chunk],
    ) -> AsyncGenerator[str, None]:
        _ = context
        api_key = await get_secret(
            self.settings.anthropic_api_key_secret_name,
            session=self.aws_session,
        )
        client = anthropic.AsyncAnthropic(api_key=api_key)
        system = _BASE_SYSTEM_MESSAGE
        if any(trigger in prompt for trigger in _JSON_OUTPUT_TRIGGERS):
            system += _JSON_OUTPUT_SYSTEM_SUFFIX
        try:
            async with client.messages.stream(
                model=_MODEL,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield text
                if hasattr(stream, "get_final_message"):
                    final_message = await stream.get_final_message()
                    usage = getattr(final_message, "usage", None)
                    if usage is not None:
                        record_llm_usage(
                            int(getattr(usage, "input_tokens", 0) or 0),
                            int(getattr(usage, "output_tokens", 0) or 0),
                        )
        except Exception as exc:
            raise ProviderUnavailableError(f"Anthropic API streaming error: {exc}") from exc
        finally:
            await client.close()
