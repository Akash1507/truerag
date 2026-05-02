import asyncio
from typing import Any

import aioboto3
import cohere

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.interfaces.embedding_provider import EmbeddingProvider
from app.utils.retry import retry
from app.utils.secrets import get_secret


_COHERE_RETRYABLE_ERRORS = (
    cohere.TooManyRequestsError,
    cohere.ServiceUnavailableError,
    cohere.InternalServerError,
    cohere.GatewayTimeoutError,
)


class CohereEmbedder(EmbeddingProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session
        self.settings = get_settings()

    @retry(max_attempts=3, backoff_factor=2, retry_on=_COHERE_RETRYABLE_ERRORS)
    async def _embed_with_retry(self, client: cohere.AsyncClient, texts: list[str]) -> list[list[float]]:
        response = await client.embed(
            texts=texts,
            model=self.settings.cohere_embedding_model,
            input_type="search_document",
        )
        embeddings = getattr(response, "embeddings", [])
        return [[float(value) for value in embedding] for embedding in embeddings]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        api_key = await get_secret(
            self.settings.cohere_api_key_secret_name,
            session=self.aws_session,
        )
        client = cohere.AsyncClient(api_key=api_key)

        try:
            return await self._embed_with_retry(client, texts)
        except _COHERE_RETRYABLE_ERRORS as exc:
            raise ProviderUnavailableError(f"Cohere API exhausted retries: {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Cohere API error: {exc}") from exc
        finally:
            client_any: Any = client
            close_fn = getattr(client_any, "close", None)
            if callable(close_fn):
                close_result = close_fn()
                if asyncio.iscoroutine(close_result):
                    await close_result
