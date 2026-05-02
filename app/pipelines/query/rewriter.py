import time

from app.models.agent import AgentDocument
from app.providers.registry import LLM_REGISTRY
from app.utils.observability import get_logger

logger = get_logger(__name__)

REWRITE_PROMPT_TEMPLATE = """You are a search query optimizer. Given the following user query, rewrite it to improve
retrieval recall by expanding acronyms, adding synonyms, and clarifying ambiguities.
Return ONLY the rewritten query - no explanation, no prefix.

Original query: {query}
Rewritten query:
"""


async def rewrite_query(query: str, agent: AgentDocument) -> str:
    t0 = time.perf_counter()
    llm_cls = LLM_REGISTRY.get(agent.llm_provider)
    if not llm_cls:
        logger.warning(
            "query_rewrite_failed",
            extra={
                "operation": "query_rewrite",
                "extra_data": {
                    "agent_id": agent.agent_id,
                    "tenant_id": agent.tenant_id,
                    "reason": f"llm provider '{agent.llm_provider}' not registered",
                },
            },
        )
        return query

    llm = llm_cls()
    prompt = REWRITE_PROMPT_TEMPLATE.format(query=query)
    try:
        rewritten_query = (await llm.generate(prompt, context=[])).strip()
        if not rewritten_query:
            rewritten_query = query
    except Exception:
        logger.warning(
            "query_rewrite_failed",
            extra={
                "operation": "query_rewrite",
                "extra_data": {
                    "agent_id": agent.agent_id,
                    "tenant_id": agent.tenant_id,
                    "reason": "llm_generate_failed",
                },
            },
        )
        rewritten_query = query

    latency_ms = round((time.perf_counter() - t0) * 1000)
    logger.info(
        "query_rewrite_complete",
        extra={
            "operation": "query_rewrite",
            "latency_ms": latency_ms,
            "extra_data": {
                "original_query_len": len(query),
                "rewritten_query_len": len(rewritten_query),
                "agent_id": agent.agent_id,
                "tenant_id": agent.tenant_id,
            },
        },
    )
    return rewritten_query
