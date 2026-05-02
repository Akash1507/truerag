# Story 5.4: Query Audit Logging

**Status:** done
**Story ID:** 5.4
**Epic:** 5 — Query, Retrieval & Answer Generation (MVP)
**Created:** 2026-05-02

---

## Story

As a Platform Admin,
I want every query event written to a tamper-evident audit log in DynamoDB as a non-blocking background task,
So that all retrieval activity is traceable by tenant, agent, and time without adding to query response latency or exposing query content (FR48, NFR11).

---

## Acceptance Criteria

**Given** a query is processed successfully or returns an error (from pipeline, not from `get_agent`)
**When** `query_service.py` completes the request
**Then** an audit log entry is written to the `truerag-audit-log` DynamoDB table with:
- `tenant_id` — string
- `agent_id` — string
- `api_key_hash` — SHA-256 hex of the caller's raw API key (use `caller.api_key_hash` from `TenantDocument` — this field already stores the SHA-256 hash)
- `query_hash` — SHA-256 hex of the **scrubbed** query text
- `timestamp` — ISO 8601 UTC string (e.g. `2026-05-02T10:00:00.000000+00:00`)
- `response_confidence` — float (0.0 if pipeline errored, actual confidence on success)
- `cache_hit` — boolean, `False` for this story (semantic cache stub not yet active)

**Given** the audit log write is dispatched
**When** `handle_query` adds it
**Then** it is performed as a FastAPI `BackgroundTask` — HTTP response is returned to caller before the write completes; slow DynamoDB writes never block the caller

**Given** the audit log entry
**When** inspected
**Then** it contains none of: query text, retrieved chunk text, generated answer, document content, or raw API key — only the fields listed above

**Given** the DynamoDB background write fails
**When** the background task handles it
**Then** failure is logged as ERROR with `operation: "audit_log_write"` and `request_id`; query response already returned to caller is unaffected; no exception propagates out of `write_audit_log`

---

## Tasks / Subtasks

- [x] **Task 1: Create `app/services/audit_service.py`**
  - [x] Implement `write_audit_log(...)` async function using `aioboto3` DynamoDB resource
  - [x] Follow `app/utils/secrets.py` module-level fallback session pattern
  - [x] Convert `response_confidence` to `Decimal` before DynamoDB write (boto3 rejects Python `float`)
  - [x] Wrap entire write in try/except; log error, never raise

- [x] **Task 2: Update `app/services/query_service.py`**
  - [x] Add `api_key_hash: str` and `background_tasks: BackgroundTasks` parameters to `handle_query`
  - [x] Call `scrub_pii(request.query)` to compute `query_hash` (double-scrub is acceptable; scrub is idempotent)
  - [x] Use `try/finally` pattern to ensure audit is scheduled even when pipeline raises
  - [x] `response_confidence` = `response.confidence` on success, `0.0` if pipeline raised (response is `None`)

- [x] **Task 3: Update `app/api/v1/query.py`**
  - [x] Inject `BackgroundTasks` from FastAPI
  - [x] Pass `api_key_hash=caller.api_key_hash` and `background_tasks=background_tasks` to `handle_query`

- [x] **Task 4: Tests**
  - [x] Create `tests/services/test_audit_service.py` — mock aioboto3 session, verify correct item written, verify error swallowed
  - [x] Update `tests/services/test_query_service.py` — verify `background_tasks.add_task` called with correct args
  - [x] Update `tests/services/test_query_service.py` — verify audit scheduled even when pipeline raises

- [x] **Task 5: Regression gate**
  - [x] Run full test suite; all previously passing tests must still pass

### Review Findings

- [x] [Review][Patch] Audit task will not run when the pipeline raises before a response is returned [app/services/query_service.py:33]
- [x] [Review][Patch] JSON output mode is not enforced at the Anthropic system-message layer [app/pipelines/query/generator.py:19]

---

## Dev Notes

### Critical: `caller.api_key_hash` IS the SHA-256 hash — do not re-hash

`TenantDocument.api_key_hash` is already the SHA-256 hex digest of the raw API key (stored at tenant registration time via `_hash_api_key` in `app/core/auth.py`). Pass it directly — do **not** hash it again.

```python
# app/core/auth.py — already exists, for reference
def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
```

```python
# app/models/tenant.py — TenantDocument already has:
api_key_hash: str  # ← this is the SHA-256 hex; use it directly
```

The route handler passes `caller.api_key_hash` (from `TenantDocument`) to `handle_query`. No raw key exposure anywhere.

---

### New file: `app/services/audit_service.py`

Follow the same module-level fallback session pattern as `app/utils/secrets.py`.

```python
import aioboto3
from datetime import UTC, datetime
from decimal import Decimal

import aioboto3

from app.core.config import get_settings
from app.utils.observability import _request_id_var, get_logger

logger = get_logger(__name__)

_default_session: aioboto3.Session = aioboto3.Session()


async def write_audit_log(
    *,
    tenant_id: str,
    agent_id: str,
    api_key_hash: str,
    query_hash: str,
    response_confidence: float,
    cache_hit: bool = False,
    session: aioboto3.Session | None = None,
) -> None:
    settings = get_settings()
    _session = session or _default_session
    timestamp = datetime.now(UTC).isoformat()
    try:
        async with _session.resource(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as dynamodb:
            table = await dynamodb.Table(settings.dynamodb_audit_table)
            await table.put_item(
                Item={
                    "tenant_id": tenant_id,
                    "sort_key": f"{timestamp}#{query_hash}",
                    "agent_id": agent_id,
                    "api_key_hash": api_key_hash,
                    "query_hash": query_hash,
                    "timestamp": timestamp,
                    "response_confidence": Decimal(str(response_confidence)),
                    "cache_hit": cache_hit,
                }
            )
    except Exception as exc:
        logger.error(
            "audit_log_write_failed",
            extra={
                "operation": "audit_log_write",
                "extra_data": {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "error": str(exc),
                    "request_id": _request_id_var.get(),
                },
            },
        )
```

**DynamoDB key schema:** partition key attribute `tenant_id`, sort key attribute `sort_key` with value `{timestamp}#{query_hash}`.

**Why `Decimal`:** `aioboto3`/`boto3` DynamoDB serializer rejects Python `float` — raises `TypeError`. Always convert: `Decimal(str(response_confidence))`. `str()` first prevents floating-point precision issues.

**Why `_request_id_var.get()`:** Background tasks run after response; `ContextVar` is inherited from the request context, so `request_id` is still available in the background coroutine.

---

### Updated: `app/services/query_service.py`

```python
import hashlib

from fastapi import BackgroundTasks

from app.models.query import QueryRequest, QueryResponse
from app.pipelines.query.pipeline import run_query_pipeline
from app.services import agent_service, audit_service
from app.utils.pii import scrub_pii


async def handle_query(
    agent_id: str,
    tenant_id: str,
    api_key_hash: str,
    request: QueryRequest,
    background_tasks: BackgroundTasks,
) -> QueryResponse:
    agent = await agent_service.get_agent(agent_id, tenant_id)
    effective_top_k = request.top_k if request.top_k is not None else agent.top_k

    scrubbed = scrub_pii(request.query)
    query_hash = hashlib.sha256(scrubbed.encode()).hexdigest()

    response: QueryResponse | None = None
    try:
        response = await run_query_pipeline(
            query=request.query,
            top_k=effective_top_k,
            agent=agent,
            filters=request.filters,
            output_format=request.output_format,
        )
        return response
    finally:
        background_tasks.add_task(
            audit_service.write_audit_log,
            tenant_id=tenant_id,
            agent_id=agent_id,
            api_key_hash=api_key_hash,
            query_hash=query_hash,
            response_confidence=response.confidence if response is not None else 0.0,
            cache_hit=False,
        )
```

**`try/finally` pattern — why:**
- `finally` always executes, so audit is scheduled whether pipeline succeeds or raises
- If `get_agent` raises (agent not found), `finally` is NOT reached — intentional; we don't audit requests that never reached the pipeline
- `response` is `None` if pipeline raised; `response.confidence` is used only on success path

**Double scrub:** `scrub_pii` is called here AND inside `run_query_pipeline`. This is acceptable — scrub is idempotent, cheap (~ms), and the alternative (threading scrubbed text out of the pipeline) is architectural complexity not worth it for this story.

---

### Updated: `app/api/v1/query.py`

```python
from fastapi import APIRouter, BackgroundTasks, Depends

from app.core.auth import get_current_tenant
from app.models.query import QueryRequest, QueryResponse
from app.models.tenant import TenantDocument
from app.services import query_service

router = APIRouter()


@router.post("/{agent_id}/query", response_model=QueryResponse, status_code=200)
async def query_agent_route(
    agent_id: str,
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> QueryResponse:
    return await query_service.handle_query(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        api_key_hash=caller.api_key_hash,
        request=request,
        background_tasks=background_tasks,
    )
```

`BackgroundTasks` is a FastAPI first-class parameter — inject it by type annotation, no `Depends()` needed.

---

### DynamoDB Table Config

`settings.dynamodb_audit_table` is already set to `"truerag-audit-log"` in `app/core/config.py`:
```python
dynamodb_audit_table: str = "truerag-audit-log"
```
No config changes needed.

`settings.aws_endpoint_url` is `None` in prod (uses real AWS) and `"http://localhost:4566"` for local LocalStack. Already handled by passing `endpoint_url=settings.aws_endpoint_url` to the client.

---

### Test Pattern: `tests/services/test_audit_service.py` (new file)

```python
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.audit_service import write_audit_log


def _make_mock_session():
    mock_table = AsyncMock()
    mock_table.put_item = AsyncMock()
    mock_dynamodb = AsyncMock()
    mock_dynamodb.Table = AsyncMock(return_value=mock_table)
    mock_resource_ctx = MagicMock()
    mock_resource_ctx.__aenter__ = AsyncMock(return_value=mock_dynamodb)
    mock_resource_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session = MagicMock()
    mock_session.resource.return_value = mock_resource_ctx
    return mock_session, mock_table


@pytest.mark.asyncio
async def test_write_audit_log_writes_correct_item():
    mock_session, mock_table = _make_mock_session()
    await write_audit_log(
        tenant_id="t1",
        agent_id="a1",
        api_key_hash="abc123hash",
        query_hash="qhash456",
        response_confidence=0.85,
        cache_hit=False,
        session=mock_session,
    )
    mock_table.put_item.assert_awaited_once()
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["tenant_id"] == "t1"
    assert item["agent_id"] == "a1"
    assert item["api_key_hash"] == "abc123hash"
    assert item["query_hash"] == "qhash456"
    assert "qhash456" in item["sort_key"]
    assert item["cache_hit"] is False
    assert item["response_confidence"] == Decimal("0.85")
    # No PII fields
    assert "query" not in item
    assert "answer" not in item
    assert "chunk_text" not in item


@pytest.mark.asyncio
async def test_write_audit_log_swallows_dynamodb_error(caplog):
    mock_session, mock_table = _make_mock_session()
    mock_table.put_item = AsyncMock(side_effect=Exception("DynamoDB unavailable"))
    # Must not raise
    await write_audit_log(
        tenant_id="t1",
        agent_id="a1",
        api_key_hash="hash",
        query_hash="qhash",
        response_confidence=0.0,
        cache_hit=False,
        session=mock_session,
    )


@pytest.mark.asyncio
async def test_write_audit_log_confidence_stored_as_decimal():
    mock_session, mock_table = _make_mock_session()
    await write_audit_log(
        tenant_id="t1", agent_id="a1", api_key_hash="h", query_hash="q",
        response_confidence=0.333, session=mock_session,
    )
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert isinstance(item["response_confidence"], Decimal)


@pytest.mark.asyncio
async def test_write_audit_log_timestamp_in_sort_key():
    mock_session, mock_table = _make_mock_session()
    await write_audit_log(
        tenant_id="t1", agent_id="a1", api_key_hash="h", query_hash="myhash",
        response_confidence=0.5, session=mock_session,
    )
    sort_key = mock_table.put_item.call_args.kwargs["Item"]["sort_key"]
    # format: {ISO8601}#myhash
    assert sort_key.endswith("#myhash")
    assert "+" in sort_key or "Z" in sort_key or "T" in sort_key  # valid ISO timestamp
```

---

### Test Pattern: `tests/services/test_query_service.py` additions

Add these tests to the existing file (import `BackgroundTasks` from `fastapi`):

```python
from fastapi import BackgroundTasks

@pytest.mark.asyncio
async def test_handle_query_schedules_audit_background_task():
    mock_response = QueryResponse(
        answer="ans", confidence=0.7, citations=[], latency_ms=100
    )
    bg = BackgroundTasks()
    with (
        patch("app.services.query_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())),
        patch("app.services.query_service.run_query_pipeline", AsyncMock(return_value=mock_response)),
        patch("app.services.query_service.audit_service.write_audit_log", AsyncMock()) as mock_audit,
    ):
        await handle_query(
            agent_id="agent-1",
            tenant_id="tenant-1",
            api_key_hash="testhash",
            request=QueryRequest(query="hello"),
            background_tasks=bg,
        )
    # BackgroundTasks.add_task registered one task
    assert len(bg.tasks) == 1


@pytest.mark.asyncio
async def test_handle_query_audit_uses_caller_api_key_hash():
    mock_response = QueryResponse(answer="ans", confidence=0.5, citations=[], latency_ms=50)
    bg = BackgroundTasks()
    with (
        patch("app.services.query_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())),
        patch("app.services.query_service.run_query_pipeline", AsyncMock(return_value=mock_response)),
    ):
        await handle_query(
            agent_id="agent-1",
            tenant_id="tenant-1",
            api_key_hash="my-sha256-hash",
            request=QueryRequest(query="test query"),
            background_tasks=bg,
        )
    task_kwargs = bg.tasks[0].kwargs
    assert task_kwargs["api_key_hash"] == "my-sha256-hash"
    assert task_kwargs["response_confidence"] == 0.5
    assert task_kwargs["cache_hit"] is False


@pytest.mark.asyncio
async def test_handle_query_audit_scheduled_even_on_pipeline_error():
    bg = BackgroundTasks()
    with (
        patch("app.services.query_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())),
        patch(
            "app.services.query_service.run_query_pipeline",
            AsyncMock(side_effect=ProviderUnavailableError("llm down")),
        ),
    ):
        with pytest.raises(ProviderUnavailableError):
            await handle_query(
                agent_id="agent-1",
                tenant_id="tenant-1",
                api_key_hash="hash",
                request=QueryRequest(query="test"),
                background_tasks=bg,
            )
    # Audit still scheduled despite error
    assert len(bg.tasks) == 1
    assert bg.tasks[0].kwargs["response_confidence"] == 0.0


@pytest.mark.asyncio
async def test_handle_query_audit_query_hash_is_sha256_of_scrubbed():
    import hashlib
    mock_response = QueryResponse(answer="ans", confidence=0.3, citations=[], latency_ms=20)
    bg = BackgroundTasks()
    with (
        patch("app.services.query_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())),
        patch("app.services.query_service.run_query_pipeline", AsyncMock(return_value=mock_response)),
        patch("app.services.query_service.scrub_pii", return_value="scrubbed text") as mock_scrub,
    ):
        await handle_query(
            agent_id="a", tenant_id="t", api_key_hash="h",
            request=QueryRequest(query="raw pii text"),
            background_tasks=bg,
        )
    mock_scrub.assert_called_once_with("raw pii text")
    expected_hash = hashlib.sha256("scrubbed text".encode()).hexdigest()
    assert bg.tasks[0].kwargs["query_hash"] == expected_hash
```

---

### Architecture Guardrails — DO NOT VIOLATE

- **Never expose raw query text, chunk text, or answer in audit log** — only `query_hash` (SHA-256 of scrubbed text)
- **Never expose raw API key** — `api_key_hash` is already the SHA-256 stored in `TenantDocument.api_key_hash`
- **Always use `aioboto3`** — never `boto3` (sync) anywhere in the async stack
- **Always use `Decimal`** for DynamoDB numeric writes — `boto3`/`aioboto3` serializer rejects Python `float`
- **Always use `get_settings().aws_endpoint_url`** for LocalStack compatibility
- **Never call `datetime.utcnow()`** — use `datetime.now(UTC)` (Python 3.12 deprecation)
- **Audit must never affect response** — `BackgroundTask` ensures this; error in `write_audit_log` is caught, never raised
- **`scrub_pii` call in `handle_query`** is intentional double-scrub — pipeline also scrubs; this is fine (idempotent)
- **`finally` block dispatches audit** — this means audit is scheduled after `get_agent` succeeds but regardless of pipeline outcome

---

### Current State (after Story 5.3)

`app/services/query_service.py`:
- `handle_query(agent_id, tenant_id, request)` — no `api_key_hash`, no `background_tasks`
- Must add both parameters; update all call sites (only `app/api/v1/query.py`)

`app/api/v1/query.py`:
- Does not inject `BackgroundTasks`; passes only `agent_id`, `tenant_id`, `request` to service
- Must inject `BackgroundTasks` and pass `caller.api_key_hash`

`app/core/config.py`:
- `dynamodb_audit_table: str = "truerag-audit-log"` already exists — no change needed

No new dependencies required — `aioboto3` already in `pyproject.toml`; `hashlib` and `decimal` are stdlib.

---

### Files to Create

| File | Action |
|------|--------|
| `app/services/audit_service.py` | **CREATE** — DynamoDB write function |
| `tests/services/test_audit_service.py` | **CREATE** — audit service tests |

### Files to Modify

| File | Change |
|------|--------|
| `app/services/query_service.py` | Add `api_key_hash`, `background_tasks` params; add `scrub_pii` + `hashlib` imports; `try/finally` audit scheduling |
| `app/api/v1/query.py` | Inject `BackgroundTasks`; pass `api_key_hash` and `background_tasks` to service |
| `tests/services/test_query_service.py` | Add 4 new tests; update existing `handle_query` calls to include new params |

---

### Regression Gate

After 5-3 implementation, test suite baseline: all prior tests pass (225+ tests). Run:
```bash
uv run pytest --tb=short -q
```
All previously passing tests must still pass after this story. The only expected changes:
- Existing `test_query_service.py` tests calling `handle_query` must be updated to pass `api_key_hash=""` and a `BackgroundTasks()` instance
- `test_query_agent_route` (in `tests/api/`) may need `BackgroundTasks` wiring if tested directly

---

### References

- [Source: epics.md#Epic 5 Story 5.4] — user story, acceptance criteria
- [Source: architecture.md#D2] — `truerag-audit-log` table; PK `tenant_id`, SK `timestamp#query_hash`
- [Source: architecture.md#D3] — `aioboto3` is the async AWS driver; use for DynamoDB
- [Source: architecture.md#Enforcement Guidelines] — never `datetime.utcnow()`; always `datetime.now(UTC)`
- [Source: app/core/config.py:dynamodb_audit_table] — table name config key
- [Source: app/core/auth.py:_hash_api_key] — `_hash_api_key` already SHA-256; `TenantDocument.api_key_hash` IS the hash
- [Source: app/utils/secrets.py] — module-level `_default_session` pattern to follow
- [Source: app/utils/observability.py:_request_id_var] — ContextVar available in background tasks
- [Source: app/services/query_service.py] — current `handle_query` signature (no `api_key_hash`)
- [Source: app/api/v1/query.py] — current route (no `BackgroundTasks`)
- [Source: 5-3 story completion notes] — regression baseline; test suite passes

---

## Dev Agent Record

### Agent Model Used
GPT-5 (Codex)

### Debug Log References
- `uv run pytest tests/services/test_audit_service.py tests/services/test_query_service.py tests/api/v1/test_query.py -q` → 24 passed
- `uv run pytest --tb=short -q` → 247 passed, 9 skipped

### Completion Notes List
- Implemented non-blocking audit log writer in `app/services/audit_service.py` using `aioboto3` with module-level fallback session.
- Ensured DynamoDB numeric serialization compatibility by converting `response_confidence` to `Decimal(str(...))`.
- Added guarded error handling in audit write path; failures are logged with `operation: audit_log_write` and request context, and never raised.
- Updated `handle_query` signature and behavior to compute SHA-256 of scrubbed query and schedule audit writes in a `finally` block.
- Updated query API route to inject `BackgroundTasks` and pass through `caller.api_key_hash` without re-hashing.
- Added new audit service unit tests and expanded query service tests for audit scheduling, hash derivation, and error-path behavior.
- Full regression suite passes after changes.

### File List
- app/services/audit_service.py
- app/services/query_service.py
- app/api/v1/query.py
- tests/services/test_audit_service.py
- tests/services/test_query_service.py

### Review Findings
None during implementation. Story moved to `review`.
