import json
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.interfaces.embedding_provider import EmbeddingProvider
from app.utils.retry import retry

_RETRYABLE_ERROR_CODES = {
    "InternalFailure",
    "ServiceUnavailableException",
    "ThrottlingException",
    "TooManyRequestsException",
}


class _RetryableBedrockError(Exception):
    pass


class BedrockEmbedder(EmbeddingProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session or aioboto3.Session()
        self.settings = get_settings()

    @retry(max_attempts=3, backoff_factor=2, retry_on=(_RetryableBedrockError,))
    async def _invoke_model_with_retry(self, client: Any, text: str) -> list[float]:
        try:
            response = await client.invoke_model(
                modelId=self.settings.bedrock_embedding_model_id,
                body=json.dumps({"inputText": text}),
                contentType="application/json",
                accept="application/json",
            )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in _RETRYABLE_ERROR_CODES:
                raise _RetryableBedrockError(str(exc)) from exc
            raise
        payload = json.loads((await response["body"].read()).decode("utf-8"))
        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            raise ProviderUnavailableError("Bedrock returned invalid embedding payload")
        return [float(value) for value in embedding]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with self.aws_session.client(
                "bedrock-runtime",
                region_name=self.settings.aws_region,
                endpoint_url=self.settings.aws_endpoint_url,
            ) as client:
                vectors: list[list[float]] = []
                for text in texts:
                    vectors.append(await self._invoke_model_with_retry(client, text))
                return vectors
        except _RetryableBedrockError as exc:
            raise ProviderUnavailableError(f"Bedrock embedding exhausted retries: {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Bedrock embedding failed: {exc}") from exc
