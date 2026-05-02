import time
from typing import Final

from rank_bm25 import BM25Okapi

from app.core.errors import ProviderUnavailableError
from app.interfaces.vector_store import VectorStore
from app.models.agent import AgentDocument
from app.models.chunk import VectorResult
from app.utils.observability import get_logger

logger = get_logger(__name__)

_MAX_CORPUS_TOP_K: Final[int] = 10_000


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    max_score = max(scores)
    min_score = min(scores)
    if max_score == min_score:
        return [1.0 if score > 0 else 0.0 for score in scores]
    scale = max_score - min_score
    return [(score - min_score) / scale for score in scores]


async def retrieve_sparse(
    query: str,
    agent: AgentDocument,
    vector_store: VectorStore,
    top_k: int,
) -> list[VectorResult]:
    t0 = time.perf_counter()
    namespace = f"{agent.tenant_id}_{agent.agent_id}"

    try:
        all_chunks = await vector_store.query(
            namespace=namespace,
            vector=[0.0],
            top_k=_MAX_CORPUS_TOP_K,
            filters=None,
        )
    except Exception as exc:  # pragma: no cover
        raise ProviderUnavailableError(f"Sparse retrieval failed to fetch corpus: {exc}") from exc

    if not all_chunks:
        logger.info(
            "sparse_retrieval_complete",
            extra={
                "operation": "sparse_retrieval",
                "latency_ms": round((time.perf_counter() - t0) * 1000),
                "extra_data": {
                    "tenant_id": agent.tenant_id,
                    "agent_id": agent.agent_id,
                    "chunk_count": 0,
                },
            },
        )
        return []

    tokenized_corpus = [result.text.split() for result in all_chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    raw_scores = bm25.get_scores(query.split()).tolist()
    normalized_scores = _normalize_scores(raw_scores)

    ranked_indices = sorted(range(len(all_chunks)), key=lambda idx: normalized_scores[idx], reverse=True)
    selected_indices = ranked_indices[:top_k]
    sparse_results = [all_chunks[idx].model_copy(update={"score": float(normalized_scores[idx])}) for idx in selected_indices]

    logger.info(
        "sparse_retrieval_complete",
        extra={
            "operation": "sparse_retrieval",
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "extra_data": {
                "tenant_id": agent.tenant_id,
                "agent_id": agent.agent_id,
                "chunk_count": len(all_chunks),
            },
        },
    )
    return sparse_results
