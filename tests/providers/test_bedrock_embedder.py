import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.core.errors import ProviderUnavailableError
from app.providers.embedding.bedrock import BedrockEmbedder


@pytest.mark.asyncio
async def test_bedrock_embedder_calls_invoke_model() -> None:
    body = AsyncMock()
    body.read = AsyncMock(return_value=json.dumps({"embedding": [0.1, 0.2]}).encode("utf-8"))
    client = AsyncMock()
    client.invoke_model = AsyncMock(return_value={"body": body})
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.client = MagicMock(return_value=client_cm)

    embedder = BedrockEmbedder(aws_session=session)
    result = await embedder.embed(["hello"])

    assert result == [[0.1, 0.2]]
    invoke_kwargs = client.invoke_model.await_args.kwargs
    assert invoke_kwargs["modelId"] == embedder.settings.bedrock_embedding_model_id
    assert json.loads(invoke_kwargs["body"]) == {"inputText": "hello"}


@pytest.mark.asyncio
async def test_bedrock_embedder_retries_retryable_client_error() -> None:
    body = AsyncMock()
    body.read = AsyncMock(return_value=json.dumps({"embedding": [0.5]}).encode("utf-8"))
    retryable = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "throttled"}},
        "InvokeModel",
    )
    client = AsyncMock()
    client.invoke_model = AsyncMock(side_effect=[retryable, {"body": body}])
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client = MagicMock(return_value=client_cm)

    with patch("asyncio.sleep", AsyncMock()):
        embedder = BedrockEmbedder(aws_session=session)
        result = await embedder.embed(["q"])

    assert result == [[0.5]]
    assert client.invoke_model.await_count == 2


@pytest.mark.asyncio
async def test_bedrock_embedder_raises_provider_unavailable_on_exception() -> None:
    client = AsyncMock()
    client.invoke_model = AsyncMock(side_effect=RuntimeError("boom"))
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client = MagicMock(return_value=client_cm)

    embedder = BedrockEmbedder(aws_session=session)
    with pytest.raises(ProviderUnavailableError, match="Bedrock embedding failed"):
        await embedder.embed(["hello"])
