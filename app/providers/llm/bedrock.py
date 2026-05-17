import json
from collections.abc import AsyncGenerator
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.interfaces.llm_provider import LLMProvider
from app.models.chunk import Chunk
from app.utils.retry import retry

_RETRYABLE_CODES = {"ThrottlingException", "ServiceUnavailableException", "TooManyRequestsException"}


class _RetryableBedrockError(Exception):
    pass


class BedrockLLMProvider(LLMProvider):
    def __init__(self, aws_session: aioboto3.Session | None = None) -> None:
        self.aws_session = aws_session or aioboto3.Session()
        self.settings = get_settings()

    @retry(max_attempts=3, backoff_factor=2, retry_on=(_RetryableBedrockError,))
    async def _generate_with_retry(self, prompt: str) -> str:
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }
        )
        try:
            async with self.aws_session.client(
                "bedrock-runtime",
                region_name=self.settings.aws_region,
                endpoint_url=self.settings.aws_endpoint_url,
            ) as client:
                response = await client.invoke_model(
                    modelId=self.settings.bedrock_llm_model_id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in _RETRYABLE_CODES:
                raise _RetryableBedrockError(str(exc)) from exc
            raise

        payload = json.loads((await response["body"].read()).decode("utf-8"))
        if "content" in payload:
            content = payload.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text")
                        if isinstance(text, str) and text:
                            return text
        if "results" in payload:
            results = payload.get("results", [])
            if isinstance(results, list):
                for block in results:
                    if isinstance(block, dict):
                        text = block.get("outputText")
                        if isinstance(text, str) and text:
                            return text
        if isinstance(payload.get("completion"), str) and payload["completion"]:
            return str(payload["completion"])
        raise ProviderUnavailableError("Bedrock API returned no text content")

    async def generate(self, prompt: str, context: list[Chunk]) -> str:
        _ = context
        try:
            return await self._generate_with_retry(prompt)
        except ProviderUnavailableError:
            raise
        except _RetryableBedrockError as exc:
            raise ProviderUnavailableError(f"Bedrock API exhausted retries: {exc}") from exc
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", "Unknown"))
            raise ProviderUnavailableError(f"Bedrock API error ({code}): {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Bedrock API error: {exc}") from exc

    async def stream_generate(
        self,
        prompt: str,
        context: list[Chunk],
    ) -> AsyncGenerator[str, None]:
        answer = await self.generate(prompt, context)
        yield answer
