from unittest.mock import AsyncMock, MagicMock, patch

import cohere
import pytest

from app.core.errors import ProviderUnavailableError
from app.providers.embedding.cohere import CohereEmbedder


@pytest.mark.asyncio
async def test_cohere_embedder_calls_embed_with_expected_model() -> None:
    response = MagicMock(embeddings=[[0.1, 0.2], [0.3, 0.4]])
    with patch("app.providers.embedding.cohere.get_secret", AsyncMock(return_value="secret")), patch(
        "app.providers.embedding.cohere.cohere.AsyncClient"
    ) as client_cls:
        client = client_cls.return_value
        client.embed = AsyncMock(return_value=response)
        client.close = AsyncMock()

        embedder = CohereEmbedder()
        result = await embedder.embed(["hello", "world"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    client.embed.assert_awaited_once_with(
        texts=["hello", "world"],
        model=embedder.settings.cohere_embedding_model,
        input_type="search_document",
    )


@pytest.mark.asyncio
async def test_cohere_embedder_retries_then_succeeds() -> None:
    response = MagicMock(embeddings=[[0.9]])
    retryable_error = cohere.TooManyRequestsError(body={"message": "rate limited"})

    with patch("app.providers.embedding.cohere.get_secret", AsyncMock(return_value="secret")), patch(
        "app.providers.embedding.cohere.cohere.AsyncClient"
    ) as client_cls, patch("asyncio.sleep", AsyncMock()):
        client = client_cls.return_value
        client.embed = AsyncMock(side_effect=[retryable_error, response])
        client.close = AsyncMock()

        embedder = CohereEmbedder()
        result = await embedder.embed(["query"])

    assert result == [[0.9]]
    assert client.embed.await_count == 2


@pytest.mark.asyncio
async def test_cohere_embedder_raises_after_retries_exhausted() -> None:
    retryable_error = cohere.TooManyRequestsError(body={"message": "unavailable"})

    with patch("app.providers.embedding.cohere.get_secret", AsyncMock(return_value="secret")), patch(
        "app.providers.embedding.cohere.cohere.AsyncClient"
    ) as client_cls, patch("asyncio.sleep", AsyncMock()):
        client = client_cls.return_value
        client.embed = AsyncMock(side_effect=retryable_error)
        client.close = AsyncMock()

        embedder = CohereEmbedder()
        with pytest.raises(ProviderUnavailableError, match="Cohere API exhausted retries"):
            await embedder.embed(["query"])

    assert client.embed.await_count == 3
