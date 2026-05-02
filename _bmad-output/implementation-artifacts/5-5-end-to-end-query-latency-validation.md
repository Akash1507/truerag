# Story 5.5: End-to-End Query Latency Validation

Status: done

## Story

As a Service Consumer,
I want query responses to consistently meet p95 latency targets under concurrent load so the API is reliable enough to power production UI integrations,
So that retrieval-as-a-service meets the latency SLA required by downstream products (NFR1, NFR2, NFR17).

## Acceptance Criteria

**AC1 — Locust load test meets SLA**
Given a query against an agent with indexed documents and `reranker: none`
When 50 concurrent queries are issued simultaneously using `locust` (defined in `scripts/locustfile.py`)
Then p95 end-to-end latency (retrieval + generation) is under 1.5 seconds; no single query exceeds 3 seconds; the locust run report is saved as `scripts/load_test_results/` and reviewed before the story is marked complete

**AC2 — Per-stage latency log entry**
Given per-stage latency tracking is wired into the query pipeline
When a query completes
Then a structured log entry is emitted with `operation: query_pipeline`, `latency_ms` (total), and per-stage breakdown fields (`retrieval_ms`, `generation_ms`) for each completed stage

**AC3 — ProviderUnavailableError → HTTP 503, no silent partial result**
Given a dependency (pgvector or Anthropic) is unavailable during a query
When `ProviderUnavailableError` is raised
Then HTTP 503 Service Unavailable is returned with the error envelope; no degraded or partial result is silently returned (NFR15)

## Tasks / Subtasks

- [x] Task 1: Wire per-stage latency tracking in `app/pipelines/query/pipeline.py`
  - [x] 1.1 Add `t_retrieval = time.perf_counter()` before `_execute_retrieval` call; compute `retrieval_ms = round((time.perf_counter() - t_retrieval) * 1000)` after
  - [x] 1.2 Add `t_generation = time.perf_counter()` before the `if results:` generation block; compute `generation_ms = round((time.perf_counter() - t_generation) * 1000)` after (timer runs even when results is empty — value will be ~0, which is correct)
  - [x] 1.3 After building `latency_ms` (already computed), add the `query_pipeline` structured log — see exact call in Dev Notes below
- [x] Task 2: Add `locust` dev dependency to `pyproject.toml`
  - [x] 2.1 Check for existing `[dependency-groups]` or `[project.optional-dependencies]` in `pyproject.toml` — none currently present
  - [x] 2.2 Add a `[dependency-groups]` section (uv-native) with `locust>=2.0.0` plus the test deps already in use (pytest, pytest-asyncio, httpx) so dev env is self-contained
  - [x] 2.3 Run `uv sync` (or `uv sync --group dev`) to install and update `uv.lock`
- [x] Task 3: Create `scripts/locustfile.py`
  - [x] 3.1 `HttpUser` reads `TRUERAG_API_KEY` and `TRUERAG_AGENT_ID` from env vars in `on_start`
  - [x] 3.2 Single `@task` that POSTs to `/v1/{agent_id}/query` with `{"query": "What are the key capabilities of this document?", "top_k": 5}` and `X-API-Key` header
  - [x] 3.3 `wait_time = between(0, 0)` — no delay between tasks to drive max concurrency
- [x] Task 4: Create `scripts/load_test_results/.gitkeep` so the results directory is tracked in git
- [x] Task 5: Add unit test for per-stage log emission to `tests/pipelines/test_query_pipeline.py`
  - [x] 5.1 `test_pipeline_emits_query_pipeline_log_with_stage_breakdown` — follow existing log-assertion pattern in that file (patch `logger.info`, collect call kwargs, assert `operation == "query_pipeline"`, `latency_ms` is int, `extra_data` has integer `retrieval_ms` and `generation_ms`)
- [x] Task 6: Add integration test for 503 at query API level
  - [x] 6.1 Check if `tests/api/v1/test_query.py` exists; if so add there, else add to `tests/pipelines/test_query_pipeline.py`
  - [x] 6.2 `test_query_endpoint_provider_unavailable_returns_503` — use real app TestClient, patch `app.services.query_service.run_query_pipeline` to raise `ProviderUnavailableError`, assert 503 + `error.code == "PROVIDER_UNAVAILABLE"`
- [x] Task 7: Manual load test validation (required before marking story done)
  - [x] 7.1 Start server: `uvicorn app.main:app --port 8000`
  - [x] 7.2 Seed a test tenant + agent: `uv run python scripts/seed_tenant.py`
  - [x] 7.3 Run load test (see Dev Notes for full command)
  - [x] 7.4 Open `scripts/load_test_results/report.html` and verify: p95 < 1500 ms, max < 3000 ms
- [x] Task 8: Regression gate — `uv run pytest --tb=short -q` — all 247+ previously passing tests must still pass

## Dev Notes

### CRITICAL: Structured Log Pattern for the `query_pipeline` Entry

The `JSONFormatter` in `app/utils/observability.py` pulls `operation` and `latency_ms` as **top-level fields** directly from the log record (via `getattr(record, ...)`). `extra_data` becomes the `"extra"` key in the JSON output.

**Exact call to add** at the end of `run_query_pipeline` (before the `return`):
```python
logger.info(
    "query_pipeline",
    extra={
        "operation": "query_pipeline",
        "latency_ms": latency_ms,
        "extra_data": {
            "retrieval_ms": retrieval_ms,
            "generation_ms": generation_ms,
            "tenant_id": agent.tenant_id,
            "agent_id": agent.agent_id,
        },
    },
)
```

Resulting JSON log output:
```json
{
  "operation": "query_pipeline",
  "latency_ms": 423,
  "extra": {"retrieval_ms": 180, "generation_ms": 230, "tenant_id": "...", "agent_id": "..."}
}
```

This pattern matches all existing log calls in the same file — do NOT deviate.

### Modified: `app/pipelines/query/pipeline.py`

Full replacement of `run_query_pipeline` body (helper functions `_execute_retrieval`, `_execute_generation`, `_compute_confidence` are **unchanged**):

```python
async def run_query_pipeline(
    query: str,
    top_k: int,
    agent: AgentDocument,
    filters: dict[str, str] | None = None,
    output_format: Literal["text", "json"] | None = None,
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

    t_retrieval = time.perf_counter()
    results = await _execute_retrieval(
        scrubbed_query=scrubbed_query,
        top_k=top_k,
        agent=agent,
        filters=filters,
    )
    retrieval_ms = round((time.perf_counter() - t_retrieval) * 1000)

    answer = ""
    t_generation = time.perf_counter()
    if results:
        answer = await _execute_generation(
            scrubbed_query=scrubbed_query,
            results=results,
            agent=agent,
            output_format=output_format,
        )
    generation_ms = round((time.perf_counter() - t_generation) * 1000)

    confidence = _compute_confidence(results)
    citations = [
        Citation(document_name=result.metadata.document_id, chunk_text=result.text, page_reference=None)
        for result in results
    ]
    latency_ms = round((time.perf_counter() - t0) * 1000)

    logger.info(
        "query_pipeline",
        extra={
            "operation": "query_pipeline",
            "latency_ms": latency_ms,
            "extra_data": {
                "retrieval_ms": retrieval_ms,
                "generation_ms": generation_ms,
                "tenant_id": agent.tenant_id,
                "agent_id": agent.agent_id,
            },
        },
    )
    return QueryResponse(answer=answer, confidence=confidence, citations=citations, latency_ms=latency_ms)
```

**Note on `generation_ms` when `results` is empty:** The timer runs before and after the `if results:` block regardless. When generation is skipped, `generation_ms` will be ~0 (measures only the `if` branch evaluation). This is correct behavior — the log entry still includes the field.

### New: `scripts/locustfile.py`

```python
import os

from locust import HttpUser, between, task


class QueryUser(HttpUser):
    wait_time = between(0, 0)

    def on_start(self) -> None:
        self.agent_id = os.environ["TRUERAG_AGENT_ID"]
        self.headers = {"X-API-Key": os.environ["TRUERAG_API_KEY"]}

    @task
    def query_agent(self) -> None:
        self.client.post(
            f"/v1/{self.agent_id}/query",
            json={"query": "What are the key capabilities of this document?", "top_k": 5},
            headers=self.headers,
        )
```

**Run command** (from project root, after seeding a tenant/agent with indexed docs):
```bash
TRUERAG_API_KEY=<api-key> TRUERAG_AGENT_ID=<agent-id> \
  locust -f scripts/locustfile.py \
  --headless -u 50 -r 50 \
  --run-time 60s \
  --host http://localhost:8000 \
  --csv scripts/load_test_results/results \
  --html scripts/load_test_results/report.html
```

**SLA thresholds** (from architecture NFR1/NFR2/NFR17):
| Metric | Threshold |
|--------|-----------|
| p95 latency | < **1,500 ms** (reranker: none) |
| Max single query | < **3,000 ms** |
| Concurrency | 50 users |

### New: `pyproject.toml` — `[dependency-groups]` section

`pyproject.toml` currently has **no** dev dependency section. Add after `[project]`:
```toml
[dependency-groups]
dev = [
    "locust>=2.0.0",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
]
```
Then: `uv sync` to update `uv.lock`. If test deps are already in `uv.lock` under a different mechanism, still add the section — uv will deduplicate.

### Test Pattern: `tests/pipelines/test_query_pipeline.py` — Per-stage Log Test

Follow the **exact** pattern of `test_pipeline_emits_embedding_and_retrieval_logs` (already in that file — it patches `logger.info` and collects call kwargs). Do **not** use `caplog` — the existing tests use the patch approach:

```python
@pytest.mark.asyncio
async def test_pipeline_emits_query_pipeline_log_with_stage_breakdown() -> None:
    agent = _make_agent()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_embedder_cls = MagicMock(return_value=mock_embedder)
    mock_vector_store = AsyncMock()
    mock_vector_store.query = AsyncMock(return_value=[_make_vector_result()])
    mock_vector_store_cls = MagicMock(return_value=mock_vector_store)
    log_calls: list[tuple[str, dict]] = []

    original_info = None

    def capture_info(msg: str, **kwargs: object) -> None:
        log_calls.append((msg, kwargs.get("extra", {})))  # type: ignore[arg-type]
        if original_info:
            original_info(msg, **kwargs)

    with (
        patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
        patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vector_store_cls}),
        patch("app.pipelines.query.pipeline.generate_answer", AsyncMock(return_value="answer")),
        patch("app.pipelines.query.pipeline.logger") as mock_logger,
    ):
        mock_logger.info.side_effect = lambda msg, **kw: log_calls.append((msg, kw.get("extra", {})))
        await run_query_pipeline("my query", 5, agent)

    pipeline_log = next(
        (extra for msg, extra in log_calls if extra.get("operation") == "query_pipeline"),
        None,
    )
    assert pipeline_log is not None, "No query_pipeline log emitted"
    assert isinstance(pipeline_log["latency_ms"], int)
    assert "retrieval_ms" in pipeline_log["extra_data"]
    assert "generation_ms" in pipeline_log["extra_data"]
    assert isinstance(pipeline_log["extra_data"]["retrieval_ms"], int)
    assert isinstance(pipeline_log["extra_data"]["generation_ms"], int)
```

### Test Pattern: Integration Test for 503 at Query API Level

Check if `tests/api/v1/test_query.py` exists. If it does, add there. If not, add to `tests/pipelines/test_query_pipeline.py`. Use the real app + TestClient pattern from `test_exception_handlers.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app as real_app
from app.core.errors import ProviderUnavailableError

_TEST_API_KEY = "test-latency-story-key"
_FAKE_TENANT = MagicMock()
_FAKE_TENANT.tenant_id = "test-tenant"
_FAKE_TENANT.api_key_hash = "hash"
_FAKE_TENANT.rate_limit_rpm = 60

def test_query_endpoint_provider_unavailable_returns_503() -> None:
    with (
        patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_FAKE_TENANT)),
        patch(
            "app.services.query_service.run_query_pipeline",
            AsyncMock(side_effect=ProviderUnavailableError("pgvector down")),
        ),
    ):
        client = TestClient(real_app, raise_server_exceptions=False)
        response = client.post(
            "/v1/some-agent/query",
            json={"query": "test query"},
            headers={"X-API-Key": _TEST_API_KEY},
        )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert "detail" not in body
```

### AC3: 503 — What Is Already Proven vs. What Is New

**Already proven (no new code needed):**
- `ProviderUnavailableError.http_status = 503` — confirmed in `app/core/errors.py`
- Unit test: `test_exception_handlers.py::test_provider_unavailable_returns_503` ✓
- Real-app integration: `test_exception_handlers.py::test_real_app_truerag_handler_registered` ✓
- Pipeline propagation: `test_query_pipeline.py::test_pipeline_embedder_provider_error_propagates` ✓
- "No silent partial result": `run_query_pipeline` has no try/except catching `ProviderUnavailableError` — it propagates naturally ✓

**New test (Task 6):** End-to-end via the actual query route (`POST /v1/{agent_id}/query`) to confirm the entire middleware stack + handler wiring holds for this specific endpoint.

### Architecture Guardrails — DO NOT VIOLATE

- **Always use `app/utils/observability.py` logger** — never `print()`, never `import logging` directly
- **`time.perf_counter()` is correct** for latency measurement — do NOT switch to datetime arithmetic
- **`latency_ms` is top-level in JSON output** because `JSONFormatter` reads `getattr(record, "latency_ms", None)` — must be passed in `extra={}`, not nested in `extra_data`
- **`retrieval_ms` / `generation_ms` go in `extra_data`** → appear under `"extra"` key in JSON
- **`scripts/` is for local dev utilities only** — `locustfile.py` must never be imported by `app/` code
- **No blocking I/O in app code** — all locust HTTP calls are in the scripts layer, completely separate from the async app stack

### Current State (after Story 5-4)

```
app/
├── api/v1/query.py           — POST /{agent_id}/query, BackgroundTasks wired to request.state
├── services/
│   ├── query_service.py      — handle_query with try/finally audit dispatch
│   └── audit_service.py      — write_audit_log to DynamoDB via BackgroundTask
├── pipelines/query/
│   ├── pipeline.py           — run_query_pipeline tracks TOTAL latency only (no per-stage yet)
│   └── generator.py          — generate_answer via AnthropicLLMProvider
├── providers/llm/anthropic.py — AnthropicLLMProvider
scripts/
└── .gitkeep                  — empty directory, no locustfile yet
```

**Test baseline (end of story 5-4):** 247 passed, 9 skipped
Run baseline before changes: `uv run pytest --tb=short -q`

### Files to Modify

| File | Change |
|------|--------|
| `app/pipelines/query/pipeline.py` | Add per-stage timers + `query_pipeline` log in `run_query_pipeline` |
| `pyproject.toml` | Add `[dependency-groups] dev` with locust + test deps |
| `tests/pipelines/test_query_pipeline.py` | Add `test_pipeline_emits_query_pipeline_log_with_stage_breakdown` |

### Files to Create

| File | Action |
|------|--------|
| `scripts/locustfile.py` | Locust `HttpUser` targeting `/v1/{agent_id}/query` |
| `scripts/load_test_results/.gitkeep` | Track the results directory in git |
| (conditional) `tests/api/v1/test_query.py` or addition | 503 integration test for query route |

### Regression Gate

```bash
uv run pytest --tb=short -q
```
Expected: all 247+ prior tests pass. New story-5-5 tests also pass.

**AC1 is manual** — cannot be validated in automated CI without a live environment. Run locally, save the HTML report, then mark story complete.

### References

- [Source: app/pipelines/query/pipeline.py] — existing `run_query_pipeline` with `t0`/`latency_ms`; `_execute_retrieval`, `_execute_generation` unchanged
- [Source: app/utils/observability.py] — `JSONFormatter` showing `latency_ms` and `operation` are top-level fields; `LatencyTracker` class exists but using raw `time.perf_counter()` is fine and consistent with existing code
- [Source: app/core/errors.py#ProviderUnavailableError] — `http_status=503` confirmed
- [Source: tests/core/test_exception_handlers.py] — 503 handler already tested; real-app integration pattern for new tests
- [Source: tests/pipelines/test_query_pipeline.py] — `test_pipeline_emits_embedding_and_retrieval_logs` shows exact logger patch pattern to follow
- [Source: _bmad-output/planning-artifacts/architecture.md] — NFR: p95 < 1.5s (no reranker), < 3s (with reranker); scalability target: 50 concurrent queries
- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.5] — canonical AC definition

## Dev Agent Record

### Agent Model Used
GPT-5 (Codex)

### Debug Log References
- `uv sync --group dev`
- `uv run pytest tests/pipelines/test_query_pipeline.py tests/api/v1/test_query.py --tb=short -q`
- `uv run pytest --tb=short -q`

### Completion Notes List
- Added per-stage retrieval/generation latency measurement and `query_pipeline` structured log emission in `run_query_pipeline`.
- Added dev dependency group with `locust`, `pytest`, `pytest-asyncio`, and `httpx`; synchronized lockfile with `uv sync --group dev`.
- Added `python-multipart` runtime dependency required by existing FastAPI form routes (regression fix surfaced during sync/test run).
- Added `scripts/locustfile.py` and `scripts/load_test_results/.gitkeep`.
- Added `test_pipeline_emits_query_pipeline_log_with_stage_breakdown` and query-route integration test `test_query_endpoint_provider_unavailable_returns_503`.
- Regression gate passed: `251 passed, 9 skipped` (with 2 existing warnings).
- Remaining manual gate: Task 7 (Locust run + report verification) is closed per user decision to complete later.
- Added `scripts/seed_tenant.py` and verified it is executable (`--help`).
- Attempted Task 7 execution by starting `uvicorn app.main:app --port 8000`, but startup failed because MongoDB is unavailable (`localhost:27017` connection refused). Marked done per user instruction; validation deferred.

### File List
- app/pipelines/query/pipeline.py
- pyproject.toml
- uv.lock
- scripts/locustfile.py
- scripts/load_test_results/.gitkeep
- tests/pipelines/test_query_pipeline.py
- tests/api/v1/test_query.py
- _bmad-output/implementation-artifacts/sprint-status.yaml
- _bmad-output/implementation-artifacts/5-5-end-to-end-query-latency-validation.md

## Change Log

- 2026-05-02: Implemented Story 5.5 Tasks 1-6 and 8; left Task 7 pending for manual Locust SLA validation.
- 2026-05-02: Marked Task 7 and story status done per user instruction; manual load validation deferred.
