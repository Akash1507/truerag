# Story 9.3: Metrics Endpoint — Prometheus & Per-Tenant Aggregation

Status: ready-for-dev

## Story

As a Platform Admin,
I want a metrics endpoint exposing per-tenant and per-agent query volume, latency, and cost in Prometheus-compatible format,
so that infrastructure monitoring tools can scrape TrueRAG metrics and platform admins have a single governance view (FR45, FR55).

## Acceptance Criteria

1. **Given** `GET /v1/metrics` **When** called **Then** the response body is valid Prometheus exposition format (`text/plain; version=0.0.4`) containing: `truerag_queries_total{tenant_id, agent_id}`, `truerag_query_latency_seconds{tenant_id, agent_id}` (histogram), `truerag_query_cost_tokens_total{tenant_id, agent_id}`, `truerag_ingestion_jobs_total{tenant_id, agent_id, status}`

2. **Given** a Prometheus scraper hitting `GET /v1/metrics` **When** it scrapes **Then** the endpoint returns within 500ms; metrics are aggregated from in-memory counters in the `truerag-api` process — not computed from raw MongoDB queries at scrape time

3. **Given** the `truerag-api` ECS task restarts **When** metrics are scraped after restart **Then** counters restart from zero for the current process lifetime; Prometheus handles counter resets natively via its `increase()` function; this reset-on-restart behaviour is documented in `docs/adrs/` as the v1 design decision — persistent counter storage is deferred to v2

4. **Given** ingestion job metrics (worker-side counts) **When** exposed **Then** they are derived from CloudWatch log metric filters on the `truerag-worker` structured logs — worker metrics are not served from the `truerag-api` in-memory counters; the `truerag_ingestion_jobs_total` metric in `GET /v1/metrics` reflects this source

5. **Given** `GET /v1/metrics` alongside `GET /v1/health` and `GET /v1/ready` **When** all three are called **Then** none require an `X-API-Key` header — they are unauthenticated infrastructure endpoints; metric labels expose only aggregate counts, never query content

## Tasks / Subtasks

- [ ] Task 1: Add `prometheus-client` to `requirements.txt` (AC: #1)
  - [ ] Add `prometheus-client>=0.20.0,<1.0.0` to `requirements.txt`
  - [ ] Add `prometheus-client>=0.20.0,<1.0.0` to `requirements-dev.txt` (needed for test assertions)

- [ ] Task 2: Create in-memory `MetricsStore` in `app/services/metrics_service.py` (AC: #1, #2)
  - [ ] Use `prometheus_client.CollectorRegistry()` — NOT the global default registry (avoids test pollution)
  - [ ] Module-level `_REGISTRY = CollectorRegistry()` singleton
  - [ ] Define four metrics on `_REGISTRY`:
    - `truerag_queries_total` — `Counter`, labels `["tenant_id", "agent_id"]`
    - `truerag_query_latency_seconds` — `Histogram`, labels `["tenant_id", "agent_id"]`, buckets `(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)`
    - `truerag_query_cost_tokens_total` — `Counter`, labels `["tenant_id", "agent_id"]`
    - `truerag_ingestion_jobs_total` — `Counter`, labels `["tenant_id", "agent_id", "status"]`, HELP text: `"Ingestion job counts (worker-side, from CloudWatch log metric filters; API-process counter is always 0)"`
  - [ ] `record_query(tenant_id, agent_id, latency_ms, total_tokens)` — increments `queries_total`, `cost_tokens_total` (by `total_tokens`), observes `latency_seconds` (latency_ms / 1000.0)
  - [ ] `generate_metrics_text() -> bytes` — calls `generate_latest(_REGISTRY)`
  - [ ] `METRICS_CONTENT_TYPE: str = CONTENT_TYPE_LATEST` — expose for router use

- [ ] Task 3: Increment metrics counters in `app/services/query_service.py` (AC: #1, #2)
  - [ ] After `run_query_pipeline()` returns successfully: call `metrics_service.record_query(tenant_id, agent_id, response.latency_ms, total_tokens)`
  - [ ] `total_tokens = prompt_tokens + completion_tokens` from `QueryCostAccumulator` (Story 9.2) via `get_cost_accumulator()`
  - [ ] If accumulator is None (e.g., test context): pass `total_tokens=0`
  - [ ] Call `record_query()` in `finally` block so it fires even on partial failures

- [ ] Task 4: Implement `GET /v1/metrics` endpoint in `app/api/v1/observability.py` (AC: #1, #2, #5)
  - [ ] `@router.get("/metrics")` handler — no auth dependency (no `Depends(get_current_tenant)`)
  - [ ] Return `Response(content=metrics_service.generate_metrics_text(), media_type=metrics_service.METRICS_CONTENT_TYPE)`
  - [ ] Use `fastapi.Response` (not `JSONResponse`) — content is raw Prometheus text, not JSON
  - [ ] Coordinate with Story 9.2: if 9.2 added a JSON `/metrics` endpoint, this task replaces it

- [ ] Task 5: Add `/v1/metrics` to `SKIP_AUTH_PATHS` in `app/core/auth.py` (AC: #5)
  - [ ] Add `"/v1/metrics"` to the `SKIP_AUTH_PATHS` frozenset (currently missing)
  - [ ] Verify `RateLimiterMiddleware` also skips unauthenticated paths (check `app/core/rate_limiter.py`)

- [ ] Task 6: Write ADR for reset-on-restart and CloudWatch ingestion source (AC: #3, #4)
  - [ ] Create `docs/adrs/adr-011-metrics-reset-on-restart.md`
  - [ ] Document: v1 design uses in-process counters that reset on ECS task restart; Prometheus `increase()` handles this natively; persistent counter storage (Redis, DynamoDB) deferred to v2
  - [ ] Document: `truerag_ingestion_jobs_total` is always 0 in the API process; real counts come from CloudWatch log metric filters on `truerag-worker` structured logs; CloudWatch exporter or Prometheus remote write covers this gap in production
  - [ ] Follow existing ADR naming: `adr-011-...` (current highest is `adr-010-extension-model-validation.md`)

- [ ] Task 7: Tests (AC: #1, #2, #5)
  - [ ] `tests/services/test_metrics_service.py`: test `record_query()` increments counters; test `generate_metrics_text()` returns valid bytes containing expected metric names
  - [ ] `tests/api/v1/test_observability.py`: test `GET /v1/metrics` returns 200 with `Content-Type: text/plain...`; test it does NOT require `X-API-Key`; test response body contains Prometheus metric names
  - [ ] Use `app/services/metrics_service._REGISTRY` to reset state between tests (`_REGISTRY._names_to_collectors.clear()` — or re-import cleanly via `importlib.reload`)

## Dev Notes

### `prometheus_client` Not in Requirements — Must Add

`prometheus_client` is NOT currently in `requirements.txt`. It is the standard Python Prometheus client library. Add:
```
prometheus-client>=0.20.0,<1.0.0
```
to both `requirements.txt` (runtime) and `requirements-dev.txt` (test assertions on format).

**Key imports:**
```python
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry
```

### Custom Registry — Do NOT Use Global

`prometheus_client` has a global `REGISTRY` that persists between tests and accumulates state across process lifetime. Use a module-level custom `CollectorRegistry()` instead:

```python
# app/services/metrics_service.py
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry

_REGISTRY = CollectorRegistry()

_queries_total = Counter(
    "truerag_queries_total",
    "Total number of queries processed",
    ["tenant_id", "agent_id"],
    registry=_REGISTRY,
)

_query_latency = Histogram(
    "truerag_query_latency_seconds",
    "Query end-to-end latency in seconds",
    ["tenant_id", "agent_id"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=_REGISTRY,
)

_cost_tokens_total = Counter(
    "truerag_query_cost_tokens_total",
    "Total tokens (prompt + completion) consumed in queries",
    ["tenant_id", "agent_id"],
    registry=_REGISTRY,
)

_ingestion_jobs_total = Counter(
    "truerag_ingestion_jobs_total",
    "Ingestion job counts (worker-side, from CloudWatch log metric filters; API-process counter is always 0)",
    ["tenant_id", "agent_id", "status"],
    registry=_REGISTRY,
)

METRICS_CONTENT_TYPE: str = CONTENT_TYPE_LATEST


def record_query(tenant_id: str, agent_id: str, latency_ms: int, total_tokens: int) -> None:
    labels = {"tenant_id": tenant_id, "agent_id": agent_id}
    _queries_total.labels(**labels).inc()
    _query_latency.labels(**labels).observe(latency_ms / 1000.0)
    if total_tokens > 0:
        _cost_tokens_total.labels(**labels).inc(total_tokens)


def generate_metrics_text() -> bytes:
    return generate_latest(_REGISTRY)
```

### `truerag_ingestion_jobs_total`: Always Zero in API Process

The `truerag-worker` runs in a separate ECS task. The API process has no channel to receive worker job counts. Per AC #4, these counts come from CloudWatch log metric filters configured in Terraform (Epic 10). For v1:
- `_ingestion_jobs_total` counter exists in `_REGISTRY` but is NEVER incremented by the API process
- The ADR (Task 6) documents this gap and the CloudWatch-based alternative
- In production, a Prometheus CloudWatch Exporter sidecar or CloudWatch Prometheus remote write provides the real values

**Do NOT attempt to call CloudWatch from the `/v1/metrics` endpoint** — this would add >100ms latency and risk the 500ms SLA.

### `GET /v1/metrics` Auth Skip — Missing from `SKIP_AUTH_PATHS`

Current `SKIP_AUTH_PATHS` in `app/core/auth.py` (line 14-21):
```python
SKIP_AUTH_PATHS: frozenset[str] = frozenset({
    "/v1/health",
    "/v1/ready",
    "/docs",
    ...
})
```
`/v1/metrics` is absent. Add it. Also verify `RateLimiterMiddleware` (`app/core/rate_limiter.py`) — if it also has a skip list, add `/v1/metrics` there too.

### FastAPI Response Type for Prometheus Text

`GET /v1/metrics` must return raw text, NOT JSON. Use `fastapi.Response`:

```python
from fastapi import APIRouter
from fastapi.responses import Response
from app.services import metrics_service

@router.get("/metrics")
async def metrics_endpoint() -> Response:
    return Response(
        content=metrics_service.generate_metrics_text(),
        media_type=metrics_service.METRICS_CONTENT_TYPE,
    )
```

`CONTENT_TYPE_LATEST` is `"text/plain; version=0.0.4; charset=utf-8"`. A Prometheus scraper validates this Content-Type.

### Dependency on Story 9.2 (QueryCostAccumulator)

`record_query()` needs `total_tokens = prompt_tokens + completion_tokens`. These come from Story 9.2's `QueryCostAccumulator`. In `query_service.py`:

```python
from app.utils.cost_tracker import get_cost_accumulator
from app.services import metrics_service

# After run_query_pipeline() returns:
acc = get_cost_accumulator()
total_tokens = (acc.prompt_tokens + acc.completion_tokens) if acc else 0
metrics_service.record_query(tenant_id, agent_id, response.latency_ms, total_tokens)
```

If implementing this story before Story 9.2, pass `total_tokens=0` as a placeholder.

### `record_query()` Placement — `finally` Block

Counter increments must fire even on query errors (to track failed queries). Place in `finally` block in `query_service.handle_query()`. If the pipeline raises, `response` may be `None` — handle this: if `latency_ms` is unavailable on error, use 0 or track separately.

### Testing Prometheus Format

Validate the response format in tests:

```python
def test_metrics_endpoint_returns_prometheus_format(client):
    resp = client.get("/v1/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "truerag_queries_total" in body
    assert "truerag_query_latency_seconds" in body
    assert "truerag_query_cost_tokens_total" in body
    assert "truerag_ingestion_jobs_total" in body
```

To reset prometheus_client counters between tests (since module-level), use `importlib.reload(metrics_service)` in a fixture, or use `monkeypatch` to replace `_REGISTRY` with a fresh `CollectorRegistry()`.

### Story 9.2 Coordination

Story 9.2 may add a `GET /v1/metrics` endpoint returning JSON cost breakdown. Story 9.3 replaces this with Prometheus format. To avoid conflict:
- Story 9.2 should implement cost aggregation in `metrics_service.py` as a function only, NOT as a FastAPI route
- Story 9.3 owns the `GET /v1/metrics` route entirely
- If Story 9.2 already added the route, Task 4 of this story replaces it

### ADR Naming

Existing ADRs in `docs/adrs/`:
- `007-rate-limiting.md`
- `008-abstract-interfaces-and-provider-registry.md`
- `adr-007-semantic-chunking-strategy.md` (different series — Epic 7 used `adr-0XX` prefix)
- `adr-008-bm25-query-time-index.md`
- `adr-009-reranking-cross-encoder-cohere.md`
- `adr-010-extension-model-validation.md`

Follow the `adr-0XX-` prefix pattern (latest). New ADR: `docs/adrs/adr-011-metrics-reset-on-restart.md`.

### Prometheus Exposition Format Sample

Expected output from `GET /v1/metrics`:
```
# HELP truerag_queries_total Total number of queries processed
# TYPE truerag_queries_total counter
truerag_queries_total{agent_id="a1",tenant_id="t1"} 42.0
# HELP truerag_query_cost_tokens_total Total tokens (prompt + completion) consumed in queries
# TYPE truerag_query_cost_tokens_total counter
truerag_query_cost_tokens_total{agent_id="a1",tenant_id="t1"} 12500.0
# HELP truerag_query_latency_seconds Query end-to-end latency in seconds
# TYPE truerag_query_latency_seconds histogram
truerag_query_latency_seconds_bucket{agent_id="a1",le="0.005",tenant_id="t1"} 0.0
truerag_query_latency_seconds_bucket{agent_id="a1",le="0.01",tenant_id="t1"} 2.0
...
truerag_query_latency_seconds_sum{agent_id="a1",tenant_id="t1"} 18.4
truerag_query_latency_seconds_count{agent_id="a1",tenant_id="t1"} 42.0
# HELP truerag_ingestion_jobs_total Ingestion job counts (worker-side, from CloudWatch log metric filters...)
# TYPE truerag_ingestion_jobs_total counter
```
Note: `prometheus_client` sorts labels alphabetically, so `agent_id` appears before `tenant_id`.

### Project Structure Notes

New files:
- `docs/adrs/adr-011-metrics-reset-on-restart.md` — ADR for v1 design decisions

Modified files:
- `requirements.txt` — add `prometheus-client>=0.20.0,<1.0.0`
- `requirements-dev.txt` — same
- `app/services/metrics_service.py` — primary implementation (created or extended from Story 9.2)
- `app/services/query_service.py` — call `metrics_service.record_query()` after pipeline
- `app/api/v1/observability.py` — add/replace `GET /v1/metrics` handler
- `app/core/auth.py` — add `"/v1/metrics"` to `SKIP_AUTH_PATHS`
- `tests/services/test_metrics_service.py` — new
- `tests/api/v1/test_observability.py` — extend (currently skipped as legacy)

### References

- FR45, FR55: metrics endpoint requirements — [Source: planning-artifacts/epics.md#Story 9.3]
- Architecture: `app/services/metrics_service.py` — "Cost + latency aggregation, Prometheus formatting" — [Source: architecture.md#line 599]
- Architecture: unauthenticated infra endpoints `/v1/metrics`, `/v1/health`, `/v1/ready` — [Source: architecture.md#line 572]
- `SKIP_AUTH_PATHS` current contents: `app/core/auth.py:14-21`
- Existing test file (skipped): `tests/api/v1/test_observability.py:1-3`
- ADR directory: `docs/adrs/` (highest existing: `adr-010-extension-model-validation.md`)
- Story 9.2 cost accumulator: `app/utils/cost_tracker.py` (created by Story 9.2)
- `prometheus_client` docs: https://github.com/prometheus/client_python

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
