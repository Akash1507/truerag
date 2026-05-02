import json
from typing import Literal

from app.core.errors import ProviderUnavailableError
from app.models.chunk import Chunk, VectorResult
from app.providers.registry import LLM_REGISTRY
from app.utils.observability import get_logger

logger = get_logger(__name__)
_JSON_OUTPUT_INSTRUCTION = (
    'Return ONLY a valid JSON object with a single key "answer" containing your response. '
    "No prose, no markdown."
)


def _build_prompt(
    query: str,
    chunks: list[Chunk],
    output_format: Literal["text", "json"] | None,
) -> str:
    context_parts = [f"[{i + 1}] {chunk.text}" for i, chunk in enumerate(chunks)]
    context_str = "\n\n".join(context_parts)
    prompt = (
        "You are a helpful assistant. Answer using only the provided context.\n"
        f"Context:\n{context_str}\n\n"
        f"Question: {query}"
    )
    if output_format == "json":
        prompt += f"\n\n{_JSON_OUTPUT_INSTRUCTION}"
    return prompt


def _validate_json_answer(answer: str) -> str:
    try:
        payload = json.loads(answer)
    except json.JSONDecodeError as exc:
        raise ProviderUnavailableError("LLM provider returned invalid JSON output") from exc

    if not isinstance(payload, dict) or set(payload) != {"answer"} or not isinstance(payload["answer"], str):
        raise ProviderUnavailableError("LLM provider returned unexpected JSON output shape")

    return json.dumps(payload)


async def generate_answer(
    query: str,
    results: list[VectorResult],
    llm_provider_name: str,
    output_format: Literal["text", "json"] | None = None,
) -> str:
    provider_cls = LLM_REGISTRY.get(llm_provider_name)
    if not provider_cls:
        raise ProviderUnavailableError(f"LLM provider '{llm_provider_name}' not registered")

    chunks = [Chunk(text=result.text, metadata=result.metadata) for result in results]
    prompt = _build_prompt(query, chunks, output_format)
    provider = provider_cls()
    answer = await provider.generate(prompt, chunks)
    if output_format == "json":
        answer = _validate_json_answer(answer)

    logger.info(
        "generation_complete",
        extra={
            "operation": "generation",
            "extra_data": {
                "provider": llm_provider_name,
                "chunk_count": len(chunks),
                "output_format": output_format or "text",
            },
        },
    )
    return answer
