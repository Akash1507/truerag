import aioboto3
import openai
from openai import AsyncOpenAI
from collections.abc import AsyncGenerator

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.interfaces.llm_provider import LLMProvider
from app.models.chunk import Chunk
from app.utils.cost_tracker import record_llm_usage
from app.utils.retry import retry
from app.utils.secrets import get_secret

_TRANSIENT_ERRORS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.InternalServerError,
)
_SYSTEM_MESSAGE = "You are a helpful assistant. Answer using only the provided context."


class OpenAILLMProvider(LLMProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session
        self.settings = get_settings()

    @retry(max_attempts=3, backoff_factor=2, retry_on=_TRANSIENT_ERRORS)
    async def _generate_with_retry(self, client: AsyncOpenAI, prompt: str) -> str:
        response = await client.chat.completions.create(
            model=self.settings.openai_llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            record_llm_usage(
                int(getattr(usage, "prompt_tokens", 0) or 0),
                int(getattr(usage, "completion_tokens", 0) or 0),
            )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ProviderUnavailableError("OpenAI API returned no text content")
        return content

    async def generate(self, prompt: str, context: list[Chunk]) -> str:
        _ = context
        api_key = await get_secret(
            self.settings.openai_api_key_secret_name,
            session=self.aws_session,
        )
        client = AsyncOpenAI(api_key=api_key)
        try:
            return await self._generate_with_retry(client, prompt)
        except ProviderUnavailableError:
            raise
        except _TRANSIENT_ERRORS as exc:
            raise ProviderUnavailableError(f"OpenAI API exhausted retries: {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"OpenAI API error: {exc}") from exc
        finally:
            await client.close()

    async def stream_generate(
        self,
        prompt: str,
        context: list[Chunk],
    ) -> AsyncGenerator[str, None]:
        _ = context
        api_key = await get_secret(
            self.settings.openai_api_key_secret_name,
            session=self.aws_session,
        )
        client = AsyncOpenAI(api_key=api_key)
        try:
            stream = await client.chat.completions.create(
                model=self.settings.openai_llm_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ],
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    record_llm_usage(
                        int(getattr(usage, "prompt_tokens", 0) or 0),
                        int(getattr(usage, "completion_tokens", 0) or 0),
                    )
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                token = getattr(delta, "content", None) if delta is not None else None
                if isinstance(token, str):
                    yield token
        except Exception as exc:
            raise ProviderUnavailableError(f"OpenAI API streaming error: {exc}") from exc
        finally:
            await client.close()
