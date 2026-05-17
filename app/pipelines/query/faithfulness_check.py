import json
from typing import Literal

from app.models.agent import AgentDocument
from app.models.chunk import VectorResult
from app.providers.registry import LLM_REGISTRY
from app.utils.observability import get_logger

logger = get_logger(__name__)

_JUDGE_SYSTEM_PROMPT = "You are a factual grounding judge. Answer only with a JSON object."
_JUDGE_USER_PROMPT = (
    'Is the following ANSWER fully supported by the CONTEXT? Return: {"supported": true/false, '
    '"confidence": 0.0-1.0, "unsupported_claims": ["..."]}'
)


def _extract_answer_content(answer: str) -> str:
    try:
        payload = json.loads(answer)
    except json.JSONDecodeError:
        return answer
    if isinstance(payload, dict) and isinstance(payload.get("answer"), str):
        return payload["answer"]
    return answer


def _build_judge_prompt(answer: str, results: list[VectorResult]) -> str:
    context_sections = [f"[{index + 1}] {result.text}" for index, result in enumerate(results[:5])]
    context = "\n\n".join(context_sections)
    answer_for_judge = _extract_answer_content(answer)
    return (
        f"System: {_JUDGE_SYSTEM_PROMPT}\n\n"
        f"User: {_JUDGE_USER_PROMPT}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"ANSWER:\n{answer_for_judge}"
    )


def _map_risk(supported: bool, confidence: float) -> Literal["low", "medium", "high"]:
    if not supported:
        return "high"
    if confidence >= 0.85:
        return "low"
    return "medium"


async def check_hallucination(
    answer: str,
    results: list[VectorResult],
    agent: AgentDocument,
) -> Literal["low", "medium", "high"] | None:
    try:
        provider_cls = LLM_REGISTRY.get(agent.llm_provider)
        if provider_cls is None:
            raise ValueError(f"LLM provider '{agent.llm_provider}' not registered")
        provider = provider_cls()
        prompt = _build_judge_prompt(answer=answer, results=results)
        raw_response = await provider.generate(prompt, context=[])
        payload = json.loads(raw_response)
        supported = bool(payload["supported"])
        confidence = float(payload.get("confidence", 0.0))
        return _map_risk(supported=supported, confidence=confidence)
    except Exception as exc:
        logger.warning(
            "hallucination_check_failed",
            extra={
                "operation": "hallucination_check",
                "extra_data": {
                    "agent_id": agent.agent_id,
                    "tenant_id": agent.tenant_id,
                    "error": str(exc),
                },
            },
        )
        return None
