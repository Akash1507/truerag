from datetime import UTC, datetime

from app.models.chunk import ChunkMetadata, VectorResult
from app.pipelines.query.rrf import reciprocal_rank_fusion


def _result(result_id: str, score: float = 0.5, doc_id: str = "doc-1", chunk_index: int = 0) -> VectorResult:
    return VectorResult(
        id=result_id,
        score=score,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id=doc_id,
            chunk_index=chunk_index,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
        text=f"text-{result_id}",
    )


def test_rrf_merges_overlapping_results_with_expected_priority() -> None:
    dense = [_result("a"), _result("b")]
    sparse = [_result("b"), _result("c")]

    merged = reciprocal_rank_fusion(dense_results=dense, sparse_results=sparse, k=60)

    assert [result.id for result in merged] == ["b", "a", "c"]


def test_rrf_includes_non_overlapping_results() -> None:
    dense = [_result("a"), _result("b")]
    sparse = [_result("c"), _result("d")]

    merged = reciprocal_rank_fusion(dense_results=dense, sparse_results=sparse, k=60)

    assert {result.id for result in merged} == {"a", "b", "c", "d"}


def test_rrf_output_sorted_descending() -> None:
    dense = [_result("x"), _result("y"), _result("z")]
    sparse = [_result("z"), _result("x")]

    merged = reciprocal_rank_fusion(dense_results=dense, sparse_results=sparse, k=60)

    assert [result.id for result in merged] == ["x", "z", "y"]


def test_rrf_deduplicates_shared_results() -> None:
    dense = [_result("shared"), _result("a")]
    sparse = [_result("shared"), _result("b")]

    merged = reciprocal_rank_fusion(dense_results=dense, sparse_results=sparse, k=60)

    assert [result.id for result in merged].count("shared") == 1
