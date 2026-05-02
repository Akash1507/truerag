from typing import Literal

from app.core.errors import ProviderUnavailableError
from app.models.agent import AgentDocument
from app.providers.registry import LLM_REGISTRY
from app.utils.observability import get_logger

logger = get_logger(__name__)

ROUTING_PROMPT_TEMPLATE = """You are a query router for a RAG system. Determine if the following query requires
document retrieval or can be answered directly from general knowledge.

Query: {query}

Respond with exactly one word: "retrieval" or "direct".
"""


async def route_query(
    query: str,
    agent: AgentDocument,
    request_id: str | None,
    tenant_id: str,
) -> Literal["retrieval", "direct"]:
    llm_cls = LLM_REGISTRY.get(agent.llm_provider)
    if not llm_cls:
        raise ProviderUnavailableError(f"LLM provider '{agent.llm_provider}' not registered")

    llm = llm_cls()
    route_raw = await llm.generate(ROUTING_PROMPT_TEMPLATE.format(query=query), context=[])
    route = route_raw.strip().lower()
    if route not in {"retrieval", "direct"}:
        route = "retrieval"

    logger.info(
        "query_route_complete",
        extra={
            "operation": "query_route",
            "request_id": request_id,
            "extra_data": {
                "route": route,
                "agent_id": agent.agent_id,
                "tenant_id": tenant_id,
            },
        },
    )
    return route
