import json
from typing import Literal

from app.core.errors import ProviderUnavailableError
from app.models.chunk import Chunk, VectorResult
from app.models.conversation import ConversationMessage
from app.providers.registry import LLM_REGISTRY
from app.utils.circuit_breaker import CircuitBreaker
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
    conversation_history: list[ConversationMessage] | None = None,
    context_window_tokens: int = 8192,
) -> str:
    context_parts = [f"[{i + 1}] {chunk.text}" for i, chunk in enumerate(chunks)]
    context_str = "\n\n".join(context_parts)
    history = conversation_history or []
    prompt = _build_conversation_prompt(
        query=query,
        context_str=context_str,
        history=history,
        context_window_tokens=context_window_tokens,
    )
    if output_format == "json":
        prompt += f"\n\n{_JSON_OUTPUT_INSTRUCTION}"
    return prompt


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def _format_history(history: list[ConversationMessage]) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for message in history:
        role = "User" if message.role == "user" else "Assistant"
        lines.append(f"{role}: {message.content}")
    return "\n".join(lines)


def _build_conversation_prompt(
    query: str,
    context_str: str,
    history: list[ConversationMessage],
    context_window_tokens: int,
) -> str:
    base_prefix = "You are a helpful assistant. Answer using only the provided context."
    question_block = f"Context:\n{context_str}\n\nQuestion: {query}"
    if not history:
        return f"{base_prefix}\n{question_block}"

    continuation_prefix = "This is a continuation of a previous conversation."
    trimmed_history = list(history)
    while True:
        history_str = _format_history(trimmed_history)
        prompt = (
            f"{continuation_prefix}\n"
            f"{base_prefix}\n\n"
            f"{history_str}\n\n"
            f"{question_block}"
        )
        if _estimate_tokens(prompt) <= context_window_tokens or not trimmed_history:
            return prompt
        trimmed_history = trimmed_history[1:]


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
    conversation_history: list[ConversationMessage] | None = None,
    context_window_tokens: int = 8192,
    circuit_breaker: CircuitBreaker | None = None,
) -> str:
    provider_cls = LLM_REGISTRY.get(llm_provider_name)
    if not provider_cls:
        raise ProviderUnavailableError(f"LLM provider '{llm_provider_name}' not registered")

    chunks = [Chunk(text=result.text, metadata=result.metadata) for result in results]
    prompt = _build_prompt(
        query,
        chunks,
        output_format,
        conversation_history=conversation_history,
        context_window_tokens=context_window_tokens,
    )
    provider = provider_cls()
    if circuit_breaker is None:
        answer = await provider.generate(prompt, chunks)
    else:
        answer = await circuit_breaker.call(provider.generate, prompt, chunks)
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
