# Story 8.5: Semantic Cache — Lookup, Store, Invalidation & Audit Logging

Status: ready-for-dev

## Story

As a Service Consumer,
I want repeated or near-identical queries served from a semantic cache with every cache hit still recorded in the audit log,
so that query latency and provider costs are reduced for common query patterns while the complete audit trail is preserved regardless of whether retrieval ran (FR37, FR38).

## Acceptance Criteria

**AC1 — Cache hit returns cached response and skips pipeline**
Given a query arrives for an agent with `semantic_cache_enabled: true`
When `semantic_cache.lookup(agent_id, query_vector, threshold)` is called before retrieval
Then if a cached entry exists with cosine similarity above `semantic_cache_threshold` (configurable per agent), the cached response is returned immediately; retrieval and generation pipeline is not executed; `latency_ms` reflects the cache hit time

**AC2 — Cache hit is recorded in audit log with `cache_hit: true`**
Given a cache hit is returned
When the response is sent to the caller
Then an audit log entry is written to DynamoDB as a `BackgroundTask` with standard fields plus `cache_hit: true` — the audit log records every query event regardless of whether retrieval ran

**AC3 — Cache miss stores response in semantic_cache table**
Given a query that misses the semantic cache
When the full retrieval + generation pipeline completes
Then the response is stored in the `semantic_cache` pgvector table with `agent_id`, `query_vector`, `query_hash`, `response`, `created_at`; namespace is scoped strictly by `agent_id`

**AC4 — Document ingest/delete invalidates the agent's cache**
Given a document is ingested or deleted for an agent
When `ingestion_worker.py` completes the operation
Then `semantic_cache.invalidate(agent_id)` is called — all cache entries for that agent are deleted; this is synchronous before ingestion status is marked `ready` (FR38)

**AC5 — semantic_cache is a dedicated pgvector table, not mixed with document vectors**
Given the semantic cache table
When inspected
Then it is the `semantic_cache` pgvector table on the same RDS instance as document chunks — a separate table; TTL enforced via `created_at` column with a periodic cleanup job

## Tasks / Subtasks

- [ ] **Task 1: Implement real semantic cache module at `app/providers/cache/semantic_cache.py`** (AC: 1, 2, 3, 4, 5)
  - [ ] Create `app/providers/cache/semantic_cache.py` (the stub is in `app/utils/semantic_cache.py` — **do not modify the stub's signature**, replace the body or create the real impl separately and update call sites)
  - [ ] Use the same `asyncpg` pool pattern as `PgVectorStore` — share the pgvector RDS connection (via `get_settings().pgvector_dsn`) but use a separate table `semantic_cache`
  - [ ] **Module-level functions** (to match existing call sites):
    ```python
    async def lookup(agent_id: str, query_vector: list[float], threshold: float) -> str | None: ...
    async def store(agent_id: str, query_vector: list[float], query_hash: str, response: str) -> None: ...
    async def invalidate(agent_id: str) -> None: ...
    ```
  - [ ] `lookup()`: query `semantic_cache` table for rows where `agent_id = $1` and cosine similarity `(embedding <=> query_vector) <= (1 - threshold)` — return the `response` string of the closest match above threshold, else `None`
  - [ ] `store()`: insert row with `(agent_id, embedding=query_vector, query_hash, response, created_at=NOW())`; use `ON CONFLICT (agent_id, query_hash) DO UPDATE SET response=EXCLUDED.response, created_at=EXCLUDED.created_at`
  - [ ] `invalidate()`: `DELETE FROM semantic_cache WHERE agent_id = $1` — already called by `app/workers/ingestion_worker.py`; this task replaces the stub body
  - [ ] **Schema** (create on startup if not exists):
    ```sql
    CREATE TABLE IF NOT EXISTS semantic_cache (
        agent_id TEXT NOT NULL,
        embedding vector,
        query_hash TEXT NOT NULL,
        response TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (agent_id, query_hash)
    );
    CREATE INDEX IF NOT EXISTS semantic_cache_agent_idx ON semantic_cache (agent_id);
    ```
  - [ ] Use `register_vector` from `pgvector.asyncpg` on the connection (same as `PgVectorStore._get_pool`)

- [ ] **Task 2: Update `app/utils/semantic_cache.py` stub to delegate to real implementation** (AC: 4)
  - [ ] The stub's `invalidate()` is imported and called in `app/workers/ingestion_worker.py`
  - [ ] Option A (preferred): Replace the stub body in `app/utils/semantic_cache.py` with real implementation (move the pgvector logic here directly — this keeps existing call sites unchanged)
  - [ ] Option B: Move real impl to `app/providers/cache/semantic_cache.py` and update import in `app/workers/ingestion_worker.py` to `from app.providers.cache import semantic_cache`
  - [ ] **Whichever option**: the final module MUST export `lookup`, `store`, and `invalidate` with the exact same signatures

- [ ] **Task 3: Integrate cache lookup into `app/services/query_service.py`** (AC: 1, 2)
  - [ ] Current `query_service.handle_query()` calls `run_query_pipeline()` directly without cache check
  - [ ] Add cache integration **before** `run_query_pipeline()`:
    ```python
    cache_hit = False
    response: QueryResponse | None = None

    if agent.semantic_cache_enabled and agent.semantic_cache_threshold:
        # Need query vector for cache lookup — embed the scrubbed query first
        # Import semantic_cache module
        from app.providers.cache import semantic_cache  # or from app.utils
        cached = await semantic_cache.lookup(agent_id, query_vector, agent.semantic_cache_threshold)
        if cached is not None:
            cache_hit = True
            response = QueryResponse(answer=cached, confidence=1.0, citations=[], latency_ms=...)
    ```
  - [ ] For cache lookup, need the query vector — embed `scrubbed` query using the agent's `embedding_provider` before the cache check
  - [ ] On cache hit: skip `run_query_pipeline()`; set `cache_hit = True`; measure `latency_ms` from request start
  - [ ] On cache miss: run pipeline as before; **after** pipeline completes, store result in cache: `await semantic_cache.store(agent_id, query_vector, query_hash, response.answer)`
  - [ ] Update the `background_tasks.add_task(audit_service.write_audit_log, ..., cache_hit=cache_hit)` to pass the correct value (already uses `cache_hit=False` — change to variable)
  - [ ] The embedding for cache lookup reuses the same `EMBEDDING_REGISTRY` pattern

- [ ] **Task 4: Verify ingestion_worker.py invalidation is correct** (AC: 4)
  - [ ] `app/workers/ingestion_worker.py` already calls `await semantic_cache.invalidate(payload.agent_id)` at line 124
  - [ ] This call must happen before the job status is set to `ready`
  - [ ] Verify the order in `ingestion_worker.py`: embed + upsert → invalidate → mark ready
  - [ ] If `invalidate` raises, log the error (already implemented in `ingestion_worker.py`) but do NOT fail the job — the ingestion succeeded; stale cache is acceptable over failed ingestion

- [ ] **Task 5: Add TTL cleanup job** (AC: 5)
  - [ ] Add a periodic cleanup function: `async def cleanup_expired_entries(max_age_hours: int = 24) -> int: ...`
  - [ ] SQL: `DELETE FROM semantic_cache WHERE created_at < NOW() - INTERVAL '$1 hours' RETURNING *`
  - [ ] For v1, the cleanup can be called at startup in `app/main.py` lifespan or triggered by the ingestion worker — a background async task that runs every N hours
  - [ ] Add `semantic_cache_ttl_hours: int = 24` to `Settings`

- [ ] **Task 6: Write unit tests** (AC: 1, 2, 3, 4)
  - [ ] `tests/providers/test_semantic_cache.py`:
    - Mock `asyncpg` pool and connection
    - `test_lookup_returns_none_on_miss` — no rows → `None`
    - `test_lookup_returns_response_on_hit` — row with distance below threshold → response string
    - `test_lookup_returns_none_below_threshold` — row exists but similarity too low → `None`
    - `test_store_inserts_row` — verify `INSERT` SQL called with correct params
    - `test_invalidate_deletes_by_agent_id` — verify `DELETE` SQL called with `agent_id`
  - [ ] `tests/services/test_query_service.py`:
    - `test_cache_hit_skips_pipeline` — mock `semantic_cache.lookup` returns value → `run_query_pipeline` not called; `cache_hit=True` in audit log
    - `test_cache_miss_calls_pipeline_and_stores` — mock `lookup` returns `None` → pipeline called; `store` called with response
    - `test_cache_disabled_skips_cache_check` — agent `semantic_cache_enabled=False` → `lookup` never called

- [ ] **Task 7: Run regression tests** (AC: 1-5)
  - [ ] `pytest tests/ -x -v --ignore=tests/integration`
  - [ ] `mypy --strict app/providers/cache/semantic_cache.py app/services/query_service.py`

## Dev Notes

### Current State — What Already Exists

**Stub** (`app/utils/semantic_cache.py`):
```python
async def invalidate(agent_id: str) -> None:
    """No-op stub. Epic 8 replaces this body with pgvector cache invalidation."""
    pass
```
Only `invalidate` is stubbed. `lookup` and `store` do not exist yet — they must be added.

**Existing call site** (`app/workers/ingestion_worker.py` line 124):
```python
from app.utils import semantic_cache
await semantic_cache.invalidate(payload.agent_id)
```
If you move the real impl to `app/providers/cache/semantic_cache.py`, update this import.

**Existing audit_service** (`app/services/audit_service.py`):
Already supports `cache_hit: bool = False` parameter — no change needed to audit service.

**Query service** (`app/services/query_service.py`):
Currently calls `run_query_pipeline()` directly and passes `cache_hit=False` to audit. This story adds cache check before the pipeline call.

**Agent model** (`app/models/agent.py`):
Already has `semantic_cache_enabled: bool` and `semantic_cache_threshold: float | None` fields.

### PgVector Table Schema

The `semantic_cache` table is SEPARATE from `document_vectors`. It lives on the same RDS instance but different table. `PgVectorStore` uses `document_vectors` — semantic cache uses `semantic_cache`.

**Why separate table** (D5 from architecture): prevents namespace confusion between document embeddings and query embeddings which may have different dimensions.

### Cosine Distance vs Similarity

pgvector `<=>` operator = cosine distance (0 = identical, 2 = opposite).
Cosine similarity = `1 - cosine_distance`.

For threshold-based lookup (threshold is similarity):
```sql
SELECT response FROM semantic_cache
WHERE agent_id = $1
  AND (embedding <=> $2::vector) <= $3   -- $3 = 1 - threshold
ORDER BY embedding <=> $2::vector
LIMIT 1;
```

Where `$3 = 1 - threshold`. If `threshold = 0.9`, then `$3 = 0.1`.

### Query Vector for Cache Lookup

Cache lookup requires embedding the query. This means `query_service.py` needs to embed before checking cache, then reuse the same vector for retrieval. Current flow:

```
scrub PII → run_query_pipeline (embeds inside) → audit log
```

New flow:
```
scrub PII → embed query → cache lookup → hit? return cached : run_query_pipeline (SKIP embed) → store cache → audit log
```

The embedding in the query pipeline (`app/pipelines/query/pipeline.py` `_execute_retrieval`) already embeds the query. To avoid double-embedding on a cache miss, pass the pre-computed `query_vector` into `run_query_pipeline`. This requires updating `run_query_pipeline`'s signature to accept optional `query_vector: list[float] | None = None` — if provided, skip the embed step.

Or simpler: accept the double embed for v1 (cache miss path). Cache hits avoid all embedding + retrieval + generation anyway.

### Reuse PgVectorStore Connection Pool

The semantic cache uses the same pgvector RDS instance. Avoid creating a second connection pool. Options:
1. Create a module-level pool in `semantic_cache.py` using the same `pgvector_dsn`
2. Pass the PgVectorStore's pool (avoid — coupling)
3. Module-level singleton pool with `asyncio.Lock` (same pattern as `PgVectorStore._pool`)

Option 3 is cleanest and consistent with existing pattern.

### Architecture Guardrails

- Semantic cache uses `agent_id` as the namespace key (not `{tenant_id}_{agent_id}`) — it's per-agent, not per-tenant-agent
- Cache stores query vectors and responses — NEVER document chunk vectors (those go in `document_vectors` via `PgVectorStore`)
- `invalidate()` is already called before ingestion status is set to `ready` — do NOT change this order
- Cache hits MUST still write audit log — zero exceptions to the audit requirement (FR38)
- `created_at` for TTL must use `datetime.now(UTC)` — never `datetime.utcnow()`

### Async Import Pattern

If importing semantic_cache inside `query_service.py`, avoid circular imports by importing at the call site or at module level (not inside `__init__`).

### Project Structure

```
app/
  utils/
    semantic_cache.py             MODIFY: replace stub body with real implementation
                                  OR keep stub that delegates to providers/cache
  providers/
    cache/
      __init__.py                 EXISTS (empty)
      semantic_cache.py           NEW (optional): real implementation here if moving from utils
  services/
    query_service.py              MODIFY: add cache lookup before pipeline + store after

tests/providers/
  test_semantic_cache.py          NEW: unit tests for cache module

app/core/
  config.py                       MODIFY: add semantic_cache_ttl_hours
```

### References

- Stub (existing call site): `app/utils/semantic_cache.py`
- Ingestion worker (invalidate caller): `app/workers/ingestion_worker.py` line 124
- Query service (integration point): `app/services/query_service.py`
- Query pipeline (embed + retrieval): `app/pipelines/query/pipeline.py`
- Audit service (cache_hit param): `app/services/audit_service.py`
- PgVectorStore (asyncpg pool pattern): `app/providers/vector_stores/pgvector.py`
- Agent model (cache fields): `app/models/agent.py`
- Config: `app/core/config.py`
- Architecture D5: `_bmad-output/planning-artifacts/architecture.md` — D5 Semantic Cache section

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
