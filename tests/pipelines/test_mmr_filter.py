from datetime import UTC, datetime

from app.models.agent import AgentDocument
from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import _apply_mmr_if_enabled, _mmr_filter


def _agent() -> AgentDocument:
    return AgentDocument.model_construct(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        mmr_enabled=True,
        mmr_lambda=0.5,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _result(result_id: str, score: float, embedding: list[float] | None) -> VectorResult:
    return VectorResult(
        id=result_id,
        score=score,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id="doc-1",
            chunk_index=0,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text=f"text-{result_id}",
        embedding=embedding,
    )


def test_mmr_filter_prefers_diverse_results_over_near_duplicates() -> None:
    results = [
        _result("dup-1", 0.99, [1.0, 0.0]),
        _result("dup-2", 0.98, [1.0, 0.0]),
        _result("dup-3", 0.97, [1.0, 0.0]),
        _result("diverse-1", 0.80, [0.0, 1.0]),
        _result("diverse-2", 0.79, [-1.0, 0.0]),
    ]

    selected = _mmr_filter(results, top_k=3, lambda_=0.5)
    selected_ids = {item.id for item in selected}

    assert "dup-1" in selected_ids
    assert {"diverse-1", "diverse-2"} & selected_ids


def test_mmr_missing_embeddings_gracefully_falls_back_to_original_results() -> None:
    agent = _agent()
    results = [
        _result("a", 0.9, None),
        _result("b", 0.8, None),
    ]

    selected = _apply_mmr_if_enabled(results=results, top_k=2, agent=agent)

    assert [item.id for item in selected] == ["a", "b"]
