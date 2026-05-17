from datetime import UTC, datetime

from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.pipeline import _rrf_merge


def _result(result_id: str, score: float) -> VectorResult:
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
    )


def test_rrf_merge_combines_rank_scores_and_deduplicates_ids() -> None:
    list_a = [_result("a", 0.6), _result("shared", 0.8)]
    list_b = [_result("shared", 0.9), _result("b", 0.7)]

    merged = _rrf_merge([list_a, list_b], top_k=3)

    assert [item.id for item in merged] == ["shared", "a", "b"]
    shared = next(item for item in merged if item.id == "shared")
    assert shared.score == 0.9
