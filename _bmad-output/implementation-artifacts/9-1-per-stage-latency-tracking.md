# Story 9.1: Per-Stage Latency Tracking

Status: ready-for-dev

## Story

As a Platform Admin,
I want per-stage latency tracked and logged for every query and ingestion operation,
so that I can identify bottlenecks across the pipeline and verify p95 targets are being met (FR47).

## Acceptance Criteria

1. **Given** a query executes through the full pipeline **When** each stage completes **Then** a structured log entry is emitted per stage with `operation`, `latency_ms`, `tenant_id`, `agent_id`, `request_id` for stages: `pii_scrub`, `cache_lookup`, `retrieval`, `reranking`, `generation`, `audit_log_write`

2. **Given** an ingestion job processes through the worker pipeline **When** each stage completes **Then** a structured log entry is emitted per stage with `latency_ms` for stages: `parse`, `pii_scrub`, `chunk`, `embed`, `upsert`

3. **Given** per-stage latency instrumentation **When** implemented **Then** it uses the latency tracker from `app/utils/observability.py` consistently across both pipelines — no inline `time.time()` calls outside of this utility

## Tasks / Subtasks

- [ ] Task 1: Add `log_stage_latency()` helper to `app/utils/observability.py` (AC: #3)
  - [ ] Function signature: `log_stage_latency(logger, operation: str, latency_ms: int) -> None`
  - [ ] Emits structured log entry; `tenant_id`, `agent_id`, `request_id` auto-populated from context vars
  - [ ] Add tests in `tests/utils/test_observability.py`

- [ ] Task 2: Set tenant/agent context vars in query API handler (AC: #1)
  - [ ] In `app/api/v1/query.py`, after resolving agent, call `set_request_context(request_id=..., tenant_id=tenant.tenant_id, agent_id=agent_id)`
  - [ ] Reset context after handler returns (use try/finally pattern matching `RequestIDMiddleware`)
  - [ ] This ensures `tenant_id` and `agent_id` appear in all downstream log entries for the request

- [ ] Task 3: Refactor `app/pipelines/query/pipeline.py` — replace inline timers with `LatencyTracker` (AC: #1, #3)
  - [ ] Remove all `import time` and `time.perf_counter()` calls
  - [ ] Instantiate `LatencyTracker()` at each stage boundary
  - [ ] Emit per-stage log entry via `log_stage_latency()` for: `pii_scrub`, `retrieval`, `reranking`, `generation`
  - [ ] Keep existing summary log at pipeline end (it is additional context; does not replace per-stage entries)

- [ ] Task 4: Add `cache_lookup` stage tracking in `app/services/query_service.py` (AC: #1)
  - [ ] Before calling `run_query_pipeline()`, wrap the cache lookup with `LatencyTracker`
  - [ ] Call `semantic_cache.lookup(agent_id, query_vector, threshold)` from `app/utils/semantic_cache.py`
  - [ ] Always emit `log_stage_latency(logger, "cache_lookup", tracker.elapsed_ms())` regardless of cache hit/miss
  - [ ] If cache hit: short-circuit and skip pipeline; if miss: continue to `run_query_pipeline()`
  - [ ] Note: requires embedding the query first to get `query_vector` for cache lookup — use `embedder.embed([scrubbed])[0]`; pass the pre-computed vector into the pipeline to avoid double-embedding

- [ ] Task 5: Add `audit_log_write` stage tracking in `app/services/audit_service.py` (AC: #1)
  - [ ] Wrap `table.put_item()` with `LatencyTracker`
  - [ ] Emit `log_stage_latency(logger, "audit_log_write", tracker.elapsed_ms())` after write (success or failure)
  - [ ] On failure path, still emit the latency entry before the existing error log

- [ ] Task 6: Refactor `app/pipelines/ingestion/pipeline.py` — add per-stage latency for all 5 stages (AC: #2, #3)
  - [ ] Remove `import time` and all `time.perf_counter()` calls
  - [ ] Add `LatencyTracker` around each sub-function: `_download_from_s3`→skip (I/O infra, not required), `parse_document`→`parse`, `_scrub_with_logging`→`pii_scrub`, `_chunk_text`→`chunk`, `_generate_embeddings`→`embed`, `_upsert_to_vector_store`→`upsert`
  - [ ] In `_scrub_with_logging()`: replace inline `t0 = time.perf_counter()` with `LatencyTracker`; move `latency_ms` to top-level extra key (not inside `extra_data`)
  - [ ] For `parse`, `chunk`, `embed`, `upsert`: add `LatencyTracker` + emit per-stage entry via `log_stage_latency()`

- [ ] Task 7: Update tests (AC: #1, #2)
  - [ ] `tests/utils/test_observability.py`: test `log_stage_latency()` emits correct JSON fields
  - [ ] `tests/pipelines/test_query_pipeline.py`: assert per-stage log entries are emitted (capture logger output via `caplog` or mock `log_stage_latency`)
  - [ ] `tests/pipelines/test_ingestion_pipeline.py` (or equivalent): same for ingestion stages

## Dev Notes

### Critical: `tenant_id`/`agent_id` Context Gap

`RequestIDMiddleware` (`app/core/middleware.py`) only sets `request_id` in context vars. `tenant_id` and `agent_id` context vars are always `None` — they are never populated. The `JSONFormatter` in `observability.py` falls back to context vars, so unless the query handler explicitly calls `set_request_context(request_id=req_id, tenant_id=..., agent_id=...)`, these fields will be `null` in all log entries.

**Fix location:** `app/api/v1/query.py` handler function — call `set_request_context()` with all three IDs after auth resolves the tenant and after the request resolves the agent ID. Use try/finally to call `reset_request_context()`.

### Critical: `cache_lookup` Stage Not Wired

The semantic cache (`app/utils/semantic_cache.py`) exists and is used for invalidation (in `ingestion_service.py` and `ingestion_worker.py`) but the query path does NOT perform a cache lookup. Story 8-5 (`semantic-cache-lookup-store-invalidation-and-audit-logging`) is `backlog`. For this story, add the lookup call and latency tracking in `query_service.py`. Even if the cache returns a miss on every call, the stage must be tracked and logged per AC #1.

The lookup requires the query embedding vector. Current flow double-embeds (once in `query_service.py` for hash, once in `pipeline.py` for retrieval). To add cache lookup without triple-embedding: embed once in `query_service.py`, pass the vector into `run_query_pipeline()` as an optional parameter.

### Inline `time.perf_counter()` Violations (Must Fix)

Architecture rule: no inline `time.time()` or `time.perf_counter()` outside `observability.py`. Current violations:

| File | Lines | Fix |
|------|-------|-----|
| `app/pipelines/query/pipeline.py` | L30, 39, 46, 48, 50, 51, 72, 74, 76, 83, 84, 91, 93, 101, 107 | Replace with `LatencyTracker` |
| `app/pipelines/query/rewriter.py` | L19, 55 | Replace with `LatencyTracker` |
| `app/pipelines/query/sparse_retriever.py` | L34, 52, 75 | Replace with `LatencyTracker` |
| `app/pipelines/ingestion/pipeline.py` | L50, 52 | Replace with `LatencyTracker` |

### Log Entry Format

The `JSONFormatter` reads `latency_ms` from `record.latency_ms` (set via `extra={"latency_ms": ...}`). For each per-stage entry the call must be:

```python
logger.info(
    "stage_name",
    extra={
        "operation": "stage_name",
        "latency_ms": tracker.elapsed_ms(),
    },
)
```

`tenant_id`, `agent_id`, `request_id` are read from context vars automatically by the formatter — do NOT pass them as extra keys (they'd be redundant and create confusion). Exception: ingestion pipeline runs in worker process where context vars are not set by HTTP middleware — pass them explicitly there.

### Proposed `log_stage_latency()` Helper

Add to `app/utils/observability.py`:

```python
def log_stage_latency(
    logger: logging.Logger,
    operation: str,
    latency_ms: int,
) -> None:
    logger.info(
        operation,
        extra={"operation": operation, "latency_ms": latency_ms},
    )
```

This keeps all stage-logging calls to a single line; formatter fills in context vars automatically.

### Ingestion Worker: Context Vars

The ingestion worker runs in a separate process/task (SQS consumer). HTTP middleware does not run there, so `request_id`, `tenant_id`, `agent_id` context vars are empty. For ingestion pipeline log entries, either:
- Pass `tenant_id` and `agent_id` as direct extra keys in each log call, OR
- Call `set_request_context(request_id=payload.job_id, tenant_id=payload.tenant_id, agent_id=payload.agent_id)` at the top of `run_ingestion_pipeline()` and reset after

The second approach is consistent with the HTTP middleware pattern.

### Required Stage Names (Exact Strings)

Query pipeline: `pii_scrub`, `cache_lookup`, `retrieval`, `reranking`, `generation`, `audit_log_write`
Ingestion pipeline: `parse`, `pii_scrub`, `chunk`, `embed`, `upsert`

Use these exact strings — Story 9.3 Prometheus metrics and Story 9.2 cost tracking key on consistent operation names.

### Testing Pattern

Use `caplog` fixture to capture log output. Example:

```python
import logging

@pytest.mark.asyncio
async def test_per_stage_latency_logged(caplog):
    with caplog.at_level(logging.INFO, logger="app.pipelines.query.pipeline"):
        await run_query_pipeline(...)
    operations = [r.operation for r in caplog.records if hasattr(r, "operation")]
    assert "pii_scrub" in operations
    assert "retrieval" in operations
```

Or mock `log_stage_latency` directly and assert `call_args_list`.

### Project Structure Notes

- `app/utils/observability.py` — add `log_stage_latency()` only; no other changes to existing API
- `app/pipelines/query/pipeline.py` — remove `import time`; all perf tracking via `LatencyTracker`
- `app/pipelines/ingestion/pipeline.py` — same; remove `import time`
- `app/pipelines/query/rewriter.py` — remove inline `time.perf_counter()`; use `LatencyTracker`
- `app/pipelines/query/sparse_retriever.py` — same
- `app/services/query_service.py` — add `cache_lookup` stage; call `set_request_context` with agent context
- `app/services/audit_service.py` — wrap DynamoDB write with `LatencyTracker`
- `tests/utils/test_observability.py` — add `log_stage_latency` tests
- `tests/pipelines/test_query_pipeline.py` — assert per-stage entries emitted
- No new files required; no new dependencies

### References

- Architecture enforcement rule: `app/utils/observability.py` — [Source: architecture.md#Enforcement Guidelines]
- FR47: per-stage latency tracked — [Source: planning-artifacts/epics.md#Story 9.1]
- `LatencyTracker` implementation: `app/utils/observability.py:62-67`
- `JSONFormatter` fields: `app/utils/observability.py:36-48`
- Inline violations to fix: `app/pipelines/query/pipeline.py:30-107`, `app/pipelines/ingestion/pipeline.py:50-52`
- Context vars: `app/utils/observability.py:11-13`
- Middleware context setting: `app/core/middleware.py:13`
- Semantic cache: `app/utils/semantic_cache.py`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
