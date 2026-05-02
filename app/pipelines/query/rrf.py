from app.models.chunk import VectorResult


def _result_key(result: VectorResult) -> str:
    return result.id


def reciprocal_rank_fusion(
    dense_results: list[VectorResult],
    sparse_results: list[VectorResult],
    k: int = 60,
) -> list[VectorResult]:
    scores: dict[str, float] = {}
    result_map: dict[str, VectorResult] = {}

    for rank, result in enumerate(dense_results, start=1):
        key = _result_key(result)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        result_map[key] = result

    for rank, result in enumerate(sparse_results, start=1):
        key = _result_key(result)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        result_map.setdefault(key, result)

    return sorted(result_map.values(), key=lambda result: scores[_result_key(result)], reverse=True)
