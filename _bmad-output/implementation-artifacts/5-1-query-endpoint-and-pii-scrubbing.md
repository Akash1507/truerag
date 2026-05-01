# Story 5.1: Query Endpoint & PII Scrubbing

Status: review

## Story

As a Service Consumer,
I want to submit a natural language query to a RAG Agent via REST and have PII stripped from my query before it reaches the retrieval pipeline,
So that my query is processed safely without sensitive data reaching the vector store or LLM (FR30, FR31).

## Acceptance Criteria

1. `POST /v1/agents/{agent_id}/query` with `{"query": "string", "top_k": integer (optional)}` accepts the request; if `top_k` is omitted the agent's configured `top_k` default is used; HTTP 200 returned after pipeline runs.
2. `scrub_pii()` is called explicitly in `app/pipelines/query/pipeline.py` between query receipt and any downstream call — never via middleware or decorator.
3. PII entities (name, email, phone) are replaced with placeholders; the scrubbed query — never the original — is passed downstream; the original query text is never written to any log.
4. Query to an agent belonging to a different tenant returns HTTP 403 Forbidden; no pipeline execution occurs.
5. Query to a non-existent agent returns HTTP 404.

## Tasks / Subtasks

- [x] Task 1: Create `QueryRequest` and `QueryResponse` Pydantic models (AC: 1, 3)
  - [x] 1.1 Create `app/models/query.py` with `QueryRequest(query: str, top_k: int | None = None)` and `QueryResponse(answer: str, confidence: float, citations: list[Citation], latency_ms: int)` where `Citation` has `document_name: str, chunk_text: str, page_reference: str | None`
  - [x] 1.2 `QueryRequest.query` must be non-empty string (use `@field_validator` or `min_length=1`)
  - [x] 1.3 `QueryResponse.confidence` is `float` in `[0.0, 1.0]` — use `Annotated[float, Field(ge=0.0, le=1.0)]`

- [x] Task 2: Create `app/pipelines/query/pipeline.py` (AC: 2, 3)
  - [x] 2.1 `run_query_pipeline(query: str, top_k: int, agent: AgentDocument) -> QueryResponse` — async function
  - [x] 2.2 Step 1: explicitly call `scrub_pii(query)` — import from `app/utils/pii.py`; this is the only scrubbing call; no middleware/decorator bypass possible
  - [x] 2.3 Step 2: log `pii_scrub` op with `{"operation": "pii_scrub", "extra_data": {"agent_id": agent.agent_id, "tenant_id": agent.tenant_id}}`
  - [x] 2.4 Step 3: return stub `QueryResponse(answer="", confidence=0.0, citations=[], latency_ms=0)` — retrieval and generation wired in stories 5.2 and 5.3
  - [x] 2.5 `latency_ms` must be measured with `time.perf_counter()` from pipeline entry to return

- [x] Task 3: Create `app/services/query_service.py` (AC: 1, 4, 5)
  - [x] 3.1 `handle_query(agent_id: str, tenant_id: str, request: QueryRequest) -> QueryResponse` — async function
  - [x] 3.2 Call `await agent_service.get_agent(agent_id, tenant_id)` — this raises `AgentNotFoundError` (404) or `ForbiddenError` (403) automatically; do NOT replicate ownership check
  - [x] 3.3 Resolve `top_k`: use `request.top_k` if provided; fall back to `agent.top_k`
  - [x] 3.4 Call `await run_query_pipeline(query=request.query, top_k=effective_top_k, agent=agent)` — import from `app/pipelines/query/pipeline`
  - [x] 3.5 Return the `QueryResponse` from pipeline

- [x] Task 4: Wire `app/api/v1/query.py` route (AC: 1, 4, 5)
  - [x] 4.1 Add `POST /{agent_id}/query` route, `response_model=QueryResponse`, `status_code=200`
  - [x] 4.2 Route signature: `(agent_id: str, request: QueryRequest, caller: TenantDocument = Depends(get_current_tenant)) -> QueryResponse`
  - [x] 4.3 Route body: single delegation call to `query_service.handle_query(agent_id, caller.tenant_id, request)` — no business logic in route

- [x] Task 5: Tests — service layer (AC: 1, 3, 4, 5)
  - [x] 5.1 Create `tests/services/test_query_service.py`
  - [x] 5.2 Happy path: mock `agent_service.get_agent` returning fake `AgentDocument` (top_k=5), mock `run_query_pipeline` returning stub `QueryResponse` — assert pipeline called with correct scrubbed-logic arguments
  - [x] 5.3 Top-k fallback: `request.top_k=None` → pipeline receives `agent.top_k`; `request.top_k=3` → pipeline receives `3`
  - [x] 5.4 Forbidden: `agent_service.get_agent` raises `ForbiddenError` → assert it propagates (do not catch)
  - [x] 5.5 Not found: `agent_service.get_agent` raises `AgentNotFoundError` → assert it propagates

- [x] Task 6: Tests — API route layer (AC: 1, 4, 5)
  - [x] 6.1 Create `tests/api/v1/test_query.py`
  - [x] 6.2 Happy path POST returns 200 with `QueryResponse` fields
  - [x] 6.3 Missing auth header returns 401
  - [x] 6.4 Cross-tenant agent returns 403 (mock `handle_query` raising `ForbiddenError`)
  - [x] 6.5 Empty `query` string returns 422 (Pydantic validation)

- [x] Task 7: Tests — PII scrubbing (AC: 2, 3)
  - [x] 7.1 Create `tests/pipelines/test_query_pipeline.py`
  - [x] 7.2 PII in query: mock `scrub_pii` to return `"<SCRUBBED>"` — assert downstream receives `"<SCRUBBED>"`, not original
  - [x] 7.3 Assert `scrub_pii` called exactly once, before any downstream call

## Dev Notes

### Architecture Guardrails (Must Follow)

- **Thin route, no logic**: `app/api/v1/query.py` delegates to `query_service` only. Never call pipeline or `scrub_pii` from route.
- **Service owns business rules**: `app/services/query_service.py` resolves `top_k`, calls ownership gate, delegates to pipeline.
- **Pipeline owns execution sequence**: `app/pipelines/query/pipeline.py` is the only place `scrub_pii` is called for the query path.
- **`agent_service.get_agent` is the ownership gate** — `get_agent(agent_id, tenant_id)` at `app/services/agent_service.py:107` raises `ForbiddenError` (403) or `AgentNotFoundError` (404) automatically. Do NOT add a manual `doc.tenant_id != tenant_id` check in `query_service`.
- **`scrub_pii` is sync**: `app/utils/pii.py:scrub_pii(text: str, *, document_id: str | None = None) -> str`. Call it directly — no `await`. Lazy-initialized Presidio engines on first call.
- **Never log original query**: after receiving `request.query`, log only hash or omit entirely. The scrubbed query is safe to pass downstream; original is not.
- **`app/pipelines/query/__init__.py` already exists** — only create `pipeline.py` inside it.
- **No `query_service.py` exists yet** in `app/services/` — create new file.

### Logging Pattern (match exactly)

```python
logger.info(
    "snake_case_op",
    extra={"operation": "fn_name", "extra_data": {"agent_id": ..., "tenant_id": ...}},
)
```

Get logger via `from app.utils.observability import get_logger; logger = get_logger(__name__)`.

### `scrub_pii` Call Site (required exact pattern)

```python
from app.utils.pii import scrub_pii

scrubbed_query = scrub_pii(query)  # sync — no await
# scrubbed_query is passed downstream, query is discarded
```

The ingestion pipeline uses the same utility at `app/pipelines/ingestion/pipeline.py:_scrub_with_logging()` — mirror that timing pattern.

### `QueryResponse` Schema (final shape — define now, fill in 5.2/5.3)

```python
class Citation(BaseModel):
    document_name: str
    chunk_text: str
    page_reference: str | None = None

class QueryResponse(BaseModel):
    answer: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    citations: list[Citation]
    latency_ms: int
```

Story 5.1 pipeline returns stub values. Stories 5.2 and 5.3 fill real values — no model changes needed.

### `top_k` Resolution Logic

```python
effective_top_k = request.top_k if request.top_k is not None else agent.top_k
```

`AgentDocument.top_k` is an int field on the Beanie document. Do not default to a hardcoded int — always fall back to agent config.

### Route Wiring Pattern (match existing `documents.py`)

```python
from app.core.auth import get_current_tenant
from app.models.tenant import TenantDocument
from app.services import query_service
from app.models.query import QueryRequest, QueryResponse

@router.post("/{agent_id}/query", response_model=QueryResponse, status_code=200)
async def query_agent_route(
    agent_id: str,
    request: QueryRequest,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> QueryResponse:
    return await query_service.handle_query(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        request=request,
    )
```

### Latency Measurement (match ingestion pattern)

```python
import time

t0 = time.perf_counter()
# ... pipeline work ...
latency_ms = round((time.perf_counter() - t0) * 1000)
```

Measure from pipeline entry (`run_query_pipeline` start) to before return.

### Project Structure Notes

New files created by this story:
- `app/models/query.py` — `QueryRequest`, `QueryResponse`, `Citation`
- `app/services/query_service.py` — `handle_query()`
- `app/pipelines/query/pipeline.py` — `run_query_pipeline()` (query `__init__.py` exists)
- `app/api/v1/query.py` — add POST route (router stub exists)
- `tests/api/v1/test_query.py`
- `tests/services/test_query_service.py`
- `tests/pipelines/test_query_pipeline.py` (create `tests/pipelines/__init__.py` if missing)

Existing files NOT touched by this story: `app/utils/pii.py`, `app/services/agent_service.py`, conftest.py.

### Test Patterns (match existing suite)

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_example():
    with (
        patch("app.services.query_service.agent_service.get_agent", AsyncMock(return_value=fake_agent)),
        patch("app.services.query_service.run_query_pipeline", AsyncMock(return_value=stub_response)),
    ):
        result = await query_service.handle_query(...)
        assert result == stub_response
```

Conftest provides `app`, `client`, `mock_beanie_collection_access` fixtures — use `client` for route-layer tests.

### References

- Architecture: query pipeline layout [Source: `_bmad-output/planning-artifacts/architecture.md` lines 606–610]
- Architecture: thin route / service / pipeline layering rule [Source: architecture.md line 731]
- Architecture: `scrub_pii()` call-site rule [Source: architecture.md ~line 527]
- `scrub_pii` implementation: [Source: `app/utils/pii.py`]
- Ingestion pipeline PII pattern: [Source: `app/pipelines/ingestion/pipeline.py:_scrub_with_logging`]
- `agent_service.get_agent` ownership gate: [Source: `app/services/agent_service.py:107`]
- Existing route pattern: [Source: `app/api/v1/documents.py`]
- Conftest fixtures: [Source: `tests/conftest.py`]
- Story 5.3 `QueryResponse` schema: [Source: `_bmad-output/planning-artifacts/epics.md` Story 5.3 AC]

## Dev Agent Record

### Agent Model Used

gpt-5

### Debug Log References

- Targeted tests: `.venv/bin/python -m pytest tests/services/test_query_service.py tests/api/v1/test_query.py tests/pipelines/test_query_pipeline.py`
- Full regression: `.venv/bin/python -m pytest`

### Completion Notes List

- Implemented query request/response models with strict validation for non-empty `query` and bounded `confidence`.
- Added async query pipeline with explicit `scrub_pii(query)` call, structured `pii_scrub` logging, latency measurement, and stub downstream execution.
- Added query service orchestration using `agent_service.get_agent` as ownership gate and `top_k` fallback logic to agent defaults.
- Wired `POST /v1/agents/{agent_id}/query` route with thin delegation to service layer.
- Added tests for service behavior, API route behavior, and PII scrubbing order/downstream data flow.
- Validated all changes through targeted and full test suites.

### File List

- app/models/query.py
- app/pipelines/query/pipeline.py
- app/services/query_service.py
- app/api/v1/query.py
- app/api/v1/__init__.py
- tests/services/test_query_service.py
- tests/api/v1/test_query.py
- tests/pipelines/test_query_pipeline.py

### Change Log

- 2026-05-02: Implemented Story 5.1 query endpoint, query service, PII-scrubbing pipeline stub, and comprehensive tests. Story moved to review.
