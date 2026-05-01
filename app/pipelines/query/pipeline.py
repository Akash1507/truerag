import time

from app.models.agent import AgentDocument
from app.models.query import QueryResponse
from app.utils.observability import get_logger
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


async def run_query_pipeline(
    query: str,
    top_k: int,
    agent: AgentDocument,
) -> QueryResponse:
    t0 = time.perf_counter()
    scrubbed_query = scrub_pii(query)
    logger.info(
        "pii_scrub",
        extra={
            "operation": "pii_scrub",
            "extra_data": {"agent_id": agent.agent_id, "tenant_id": agent.tenant_id},
        },
    )
    response = await _execute_stub(scrubbed_query=scrubbed_query, top_k=top_k, agent=agent)
    latency_ms = round((time.perf_counter() - t0) * 1000)
    return response.model_copy(update={"latency_ms": latency_ms})


async def _execute_stub(scrubbed_query: str, top_k: int, agent: AgentDocument) -> QueryResponse:
    _ = scrubbed_query
    _ = top_k
    _ = agent
    return QueryResponse(answer="", confidence=0.0, citations=[], latency_ms=0)
