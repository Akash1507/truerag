import pytest
from unittest.mock import AsyncMock, patch
import openai
from app.providers.embedding.openai import OpenAIEmbedder
from app.core.errors import ProviderUnavailableError

@pytest.mark.asyncio
async def test_openai_embedder_success():
    mock_response = AsyncMock()
    mock_response.data = [
        AsyncMock(embedding=[0.1, 0.2, 0.3]),
        AsyncMock(embedding=[0.4, 0.5, 0.6]),
    ]
    
    with patch("app.providers.embedding.openai.get_secret", return_value="fake-key") as mock_get_secret:
        with patch("app.providers.embedding.openai.AsyncOpenAI") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            mock_client.close = AsyncMock()
            
            embedder = OpenAIEmbedder()
            texts = ["hello", "world"]
            vectors = await embedder.embed(texts)
            
            assert len(vectors) == 2
            assert vectors[0] == [0.1, 0.2, 0.3]
            assert vectors[1] == [0.4, 0.5, 0.6]
            mock_get_secret.assert_called_once()
            mock_client.embeddings.create.assert_called_once_with(
                input=texts, model="text-embedding-3-small"
            )

@pytest.mark.asyncio
async def test_openai_embedder_retry_success():
    mock_response = AsyncMock()
    mock_response.data = [AsyncMock(embedding=[0.1])]
    
    with patch("app.providers.embedding.openai.get_secret", return_value="fake-key"):
        with patch("app.providers.embedding.openai.AsyncOpenAI") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            # Fail once with RateLimitError, then succeed
            mock_client.embeddings.create = AsyncMock(side_effect=[
                openai.RateLimitError("Rate limit", response=AsyncMock(), body={}),
                mock_response
            ])
            mock_client.close = AsyncMock()
            
            embedder = OpenAIEmbedder()
            with patch("asyncio.sleep", return_value=None): # Speed up test
                vectors = await embedder.embed(["test"])
            
            assert vectors == [[0.1]]
            assert mock_client.embeddings.create.call_count == 2

@pytest.mark.asyncio
async def test_openai_embedder_exhaustion():
    with patch("app.providers.embedding.openai.get_secret", return_value="fake-key"):
        with patch("app.providers.embedding.openai.AsyncOpenAI") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.embeddings.create = AsyncMock(side_effect=openai.RateLimitError("Rate limit", response=AsyncMock(), body={}))
            mock_client.close = AsyncMock()
            
            embedder = OpenAIEmbedder()
            with patch("asyncio.sleep", return_value=None):
                with pytest.raises(ProviderUnavailableError) as exc_info:
                    await embedder.embed(["test"])
                
                assert "OpenAI API exhausted retries" in str(exc_info.value)
                assert mock_client.embeddings.create.call_count == 3

@pytest.mark.asyncio
async def test_openai_embedder_empty_input():
    embedder = OpenAIEmbedder()
    vectors = await embedder.embed([])
    assert vectors == []
