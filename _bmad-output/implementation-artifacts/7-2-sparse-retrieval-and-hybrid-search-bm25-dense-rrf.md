# Story 7.2: Sparse Retrieval & Hybrid Search (BM25 + Dense + RRF)

Status: done

## Story

As a Tenant Developer,
I want to configure hybrid search combining BM25 sparse retrieval with dense vector search merged via Reciprocal Rank Fusion,
so that retrieval quality improves for queries where keyword precision matters alongside semantic similarity (FR24).

## Acceptance Criteria

**AC1 — Sparse-only retrieval via BM25**
Given an agent configured with `retrieval_mode: sparse`
When a query is executed
Then BM25 keyword retrieval is performed against the agent's indexed chunks; results are returned ranked by BM25 score; no dense vector query is issued

**AC2 — BM25 index built at query time from vector store chunks**
Given BM25 sparse retrieval is performed
When the BM25 index is built
Then it is constructed at query time from the agent's chunk texts fetched from the vector store — no separate BM25 index store is maintained; this is a known performance tradeoff documented in an ADR in `docs/adrs/`

**AC3 — Hybrid retrieval merges BM25 + dense via RRF**
Given an agent configured with `retrieval_mode: hybrid`
When a query is executed
Then both BM25 sparse retrieval and dense vector retrieval are run in parallel; results are merged using Reciprocal Rank Fusion (RRF); the final ranked list is returned to the reranker or generator stage

**AC4 — Config change takes effect on next request (no restart)**
Given `retrieval_mode` is changed from `dense` to `hybrid` via `PATCH /v1/agents/{agent_id}/config`
When the next query arrives
Then the new retrieval mode is active with no service restart; the config change takes effect on the next request via the request-scoped config cache

## Tasks / Subtasks

- [x] **Task 1: Write ADR for BM25 at-query-time index approach** (before implementation)
  - [x] Create `docs/adrs/adr-008-bm25-query-time-index.md`
  - [x] Document tradeoff: at-query-time BM25 index (all chunks fetched per query) vs. persistent BM25 index (separate store, higher infra complexity)
  - [x] Document chosen approach: query-time index using `rank_bm25` library; no new infrastructure dependency; acceptable for MVP-scale corpora; known O(N) latency per query; performance measured and compared to dense-only SLA

- [x] **Task 2: Implement BM25SparseRetriever**
  - [x] File: `app/pipelines/query/sparse_retriever.py`
  - [x] Function `async def retrieve_sparse(query: str, agent: AgentDocument, vector_store: VectorStore, top_k: int) -> list[VectorResult]`
  - [x] Step 1: Fetch all chunks for the agent's namespace from the vector store using a broad query (fetch all — use `vector_store.query(namespace, zero_vector, top_k=10000, filters=None)` or a dedicated `list_all` approach if available)
  - [x] Step 2: Build `BM25Okapi` index from chunk texts using `rank_bm25`
  - [x] Step 3: Tokenize query (whitespace split); score all chunks; return top `top_k` as `list[VectorResult]` (set `score` field from BM25 score, normalized to 0–1 range)
  - [x] Log: `operation: sparse_retrieval`, `agent_id`, `tenant_id`, `chunk_count`, `latency_ms` via `app/utils/observability.py`

- [x] **Task 3: Implement RRF merger**
  - [x] File: `app/pipelines/query/rrf.py`
  - [x] Function `def reciprocal_rank_fusion(dense_results: list[VectorResult], sparse_results: list[VectorResult], k: int = 60) -> list[VectorResult]`
  - [x] RRF formula: `score(d) = sum(1 / (k + rank(d)))` where rank is 1-based position in each list
  - [x] Deduplicate by `chunk_id` (or `document_id + chunk_index` composite key from `VectorResult`)
  - [x] Return merged list sorted descending by RRF score; truncate to `top_k` (caller's responsibility)
  - [x] Pure function — no I/O, fully unit-testable

- [x] **Task 4: Update query pipeline to handle all three retrieval modes**
  - [x] File: `app/pipelines/query/pipeline.py`
  - [x] Current: only `dense` retrieval (direct `vector_store.query()`)
  - [x] Add branching on `agent.retrieval_mode`:
    - `"dense"` → existing dense path (unchanged)
    - `"sparse"` → call `retrieve_sparse()`
    - `"hybrid"` → run dense and sparse in parallel via `asyncio.gather()`; merge with `reciprocal_rank_fusion()`; pass merged list to reranker stage
  - [x] Wrap new retrieval paths in the same `time.perf_counter()` instrumentation used for `retrieval_ms` in story 5-5
  - [x] Raise `ProviderUnavailableError` (from `app/core/errors.py`) on retrieval failure — do NOT return partial results

- [x] **Task 5: Add rank_bm25 dependency**
  - [x] `pyproject.toml` / `requirements.txt`: add `rank-bm25>=0.2`

- [x] **Task 6: Write tests**
  - [x] `tests/pipelines/query/test_sparse_retriever.py`:
    - Test: corpus with known BM25 scores → top-k returned correctly
    - Test: empty corpus → returns `[]`
    - Test: `top_k` respected
    - Use `AsyncMock` for `vector_store.query()`
  - [x] `tests/pipelines/query/test_rrf.py`:
    - Test: overlapping results from both lists are merged with RRF formula
    - Test: non-overlapping results from both lists are all included
    - Test: output sorted descending by RRF score
    - Test: deduplication when same chunk appears in both lists
    - Pure unit test — no I/O
  - [x] `tests/pipelines/query/test_pipeline.py` — add cases:
    - Test: `retrieval_mode="sparse"` → `vector_store.query()` not called for dense embed; sparse retriever called
    - Test: `retrieval_mode="hybrid"` → both dense and sparse called; RRF applied
    - Test: `retrieval_mode="dense"` → existing behavior unchanged (regression test)

## Dev Notes

### Current State (after Story 5-5)

- `app/pipelines/query/pipeline.py` — only `dense` retrieval implemented; `agent.retrieval_mode` field exists but only `"dense"` path exists
- `app/models/agent.py` — `VALID_RETRIEVAL_MODES = {"dense", "sparse", "hybrid"}` — all three already validated
- `app/interfaces/vector_store.py` — `query(namespace, vector, top_k, filters)` is the only retrieval method; no `list_all` method
- `app/providers/rerankers/passthrough.py` — `PassthroughReranker` exists; reranker stage already wired in pipeline (story 5-3)

### BM25 "Fetch All" Pattern

For BM25, you need all chunk texts for the agent's namespace. The `VectorStore.query()` interface accepts a vector — pass a zero vector (all-zeros, same dimensionality as embeddings) with a very large `top_k` (e.g., 10000) to approximate a full scan. This is documented as a known limitation in the ADR. If `VectorStore.query()` raises on zero-vector, fall back to: embed the query normally, fetch `top_k=10000` using the real query vector (retrieves most similar chunks — imperfect BM25 corpus but acceptable for MVP).

```python
zero_vector = [0.0] * EMBEDDING_DIM  # e.g., 1536 for OpenAI ada-002
all_chunks = await vector_store.query(namespace, zero_vector, top_k=10000, filters=None)
```

### RRF Formula Reference

```python
def reciprocal_rank_fusion(
    dense_results: list[VectorResult],
    sparse_results: list[VectorResult],
    k: int = 60,
) -> list[VectorResult]:
    scores: dict[str, float] = {}
    result_map: dict[str, VectorResult] = {}
    for rank, result in enumerate(dense_results, start=1):
        key = result.chunk_id  # or f"{result.document_id}_{result.chunk_index}"
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        result_map[key] = result
    for rank, result in enumerate(sparse_results, start=1):
        key = result.chunk_id
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        result_map.setdefault(key, result)
    return sorted(result_map.values(), key=lambda r: scores[r.chunk_id], reverse=True)
```

### Architecture Guardrails — DO NOT VIOLATE

- Never bypass `app/providers/registry.py` — chunker/embedder/vector-store resolved via registry
- Parallel BM25 + dense retrieval MUST use `asyncio.gather()` — no sequential blocking
- Always use `app/utils/observability.py` logger with structured fields
- `ProviderUnavailableError` → HTTP 503 (already wired in `app/core/exception_handlers.py`)
- Config is request-scoped (loaded via `Depends()` per request) — retrieval_mode change takes effect immediately on next request; no caching to bust
- Never introduce a new infrastructure component (no Redis, no Elasticsearch) — BM25 is purely in-process

### Project Structure Notes

```
app/pipelines/query/
├── pipeline.py          # MODIFY: add sparse/hybrid branching
├── sparse_retriever.py  # NEW: BM25 sparse retrieval logic
└── rrf.py               # NEW: Reciprocal Rank Fusion merger

docs/adrs/
└── adr-008-bm25-query-time-index.md  # NEW (write before implementation)

tests/pipelines/query/
├── test_sparse_retriever.py  # NEW
├── test_rrf.py               # NEW
└── test_pipeline.py          # MODIFY: add sparse/hybrid test cases
```

### References

- `app/pipelines/query/pipeline.py` — current query pipeline (integration point)
- `app/interfaces/vector_store.py` — `query()` signature
- `app/interfaces/reranker.py` — `rerank()` signature (output of retrieval feeds into this)
- `app/models/agent.py` — `VALID_RETRIEVAL_MODES`, `AgentDocument` fields
- `app/core/errors.py` — `ProviderUnavailableError`
- Story 5-5 dev notes — per-stage latency instrumentation pattern (`time.perf_counter()`, `retrieval_ms` in `extra_data`)
- `rank-bm25` PyPI: https://pypi.org/project/rank-bm25/

## Dev Agent Record

### Agent Model Used
GPT-5 Codex

### Debug Log References
Targeted pytest execution for `tests/pipelines/query/` test modules added in this story.

### Completion Notes List
- Implemented sparse BM25 retriever using `rank-bm25`, including score normalization and structured observability logging.
- Implemented pure RRF merger with deduplication by vector result id.
- Updated retrieval pipeline to support `dense`, `sparse`, and `hybrid` modes, with hybrid parallelized using `asyncio.gather`.
- Preserved ProviderUnavailableError behavior by converting retrieval path failures to 503-class domain errors.
- Added focused unit tests for sparse retrieval, RRF behavior, and retrieval-mode branching.

### File List
- `app/pipelines/query/pipeline.py` — modified
- `app/pipelines/query/sparse_retriever.py` — created
- `app/pipelines/query/rrf.py` — created
- `docs/adrs/adr-008-bm25-query-time-index.md` — created
- `tests/pipelines/query/test_sparse_retriever.py` — created
- `tests/pipelines/query/test_rrf.py` — created
- `tests/pipelines/query/test_pipeline.py` — created

## Change Log

| Date | Change |
|------|--------|
| 2026-05-02 | Story created |
| 2026-05-02 | Story implemented end-to-end (sparse + hybrid retrieval, RRF, tests, ADR, deps) |
