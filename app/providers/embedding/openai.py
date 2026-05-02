import aioboto3
import openai
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.interfaces.embedding_provider import EmbeddingProvider
from app.utils.cost_tracker import record_embedding_call
from app.utils.retry import retry
from app.utils.secrets import get_secret


class OpenAIEmbedder(EmbeddingProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session
        self.settings = get_settings()

    @retry(
        max_attempts=3,
        backoff_factor=2,
        retry_on=(
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.InternalServerError,
        ),
    )
    async def _embed_with_retry(self, client: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
        response = await client.embeddings.create(
            input=texts, model="text-embedding-3-small"
        )
        return [item.embedding for item in response.data]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        api_key = await get_secret(
            self.settings.openai_api_key_secret_name, session=self.aws_session
        )
        
        client = AsyncOpenAI(api_key=api_key)
        
        try:
            vectors = await self._embed_with_retry(client, texts)
            record_embedding_call()
            return vectors
        except (openai.RateLimitError, openai.APITimeoutError, openai.InternalServerError) as exc:
            raise ProviderUnavailableError(f"OpenAI API exhausted retries: {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"OpenAI API error: {exc}") from exc
        finally:
            await client.close()
