# Story 1.7: Per-Tenant Rate Limiting

Status: done

## Story

As an AI Platform Engineer,
I want an in-process fixed-window rate limiter enforcing per-tenant per-minute request limits,
So that no single tenant exhausts platform resources and over-limit requests receive a clear 429 response (FR52).

## Acceptance Criteria

**AC1:** Given a tenant's request count is below their configured per-minute limit
When a request arrives
Then it passes through to the handler without restriction

**AC2:** Given a tenant configured with limit N requests per minute
When the (N+1)th request arrives within the same 1-minute window
Then HTTP 429 Too Many Requests is returned with the error envelope and `ErrorCode.RATE_LIMIT_EXCEEDED`; no business logic executes

**AC3:** Given a tenant with no explicit limit set in MongoDB
When a request arrives
Then the default limit from `app/core/config.py` (`default_rate_limit_rpm`) is applied

**AC4:** Given the in-process counter behaviour
When documented in `docs/adrs/`
Then the ADR explicitly states that per-replica enforcement is the v1 behaviour and Redis-backed global enforcement is deferred to v2

## Tasks / Subtasks

- [x] Task 1: Create `app/core/rate_limiter.py` — in-process fixed-window middleware (AC1, AC2, AC3)
  - [x] 1.1 Create `app/core/rate_limiter.py`
  - [x] 1.2 Define module-level store: `_counters: dict[str, tuple[float, int]] = {}` — key: `tenant_id`, value: `(window_start: float, count: int)`
  - [x] 1.3 Define `_rate_limit_error(request_id: str) -> JSONResponse` — builds standard error envelope with `ErrorCode.RATE_LIMIT_EXCEEDED`, HTTP 429; mirrors `_auth_error` pattern from `app/core/auth.py`
  - [x] 1.4 Implement `class RateLimiterMiddleware(BaseHTTPMiddleware):`
    - [x] 1.4.1 If `not hasattr(request.state, "tenant")`: call `await call_next(request)` and return — handles SKIP_AUTH_PATHS where tenant is not set
    - [x] 1.4.2 Read `tenant: TenantDocument = request.state.tenant`
    - [x] 1.4.3 Read `limit: int = tenant.rate_limit_rpm if tenant.rate_limit_rpm > 0 else get_settings().default_rate_limit_rpm`
    - [x] 1.4.4 Implement fixed-window check: `now = time.monotonic()` — use `time.monotonic()` not `time.time()` (monotonic is immune to clock adjustments)
    - [x] 1.4.5 Check `_counters.get(tenant.tenant_id)` — if entry absent OR `now - window_start >= 60.0`: set new window `_counters[tenant.tenant_id] = (now, 1)` and proceed
    - [x] 1.4.6 Else if `count >= limit`: return `_rate_limit_error(request_id)` — 429 BEFORE calling `call_next`
    - [x] 1.4.7 Else: increment `_counters[tenant.tenant_id] = (window_start, count + 1)` and proceed with `await call_next(request)`
    - [x] 1.4.8 Read `request_id = getattr(request.state, "request_id", "unknown")` for error response
    - [x] 1.4.9 Log at WARNING when rate limit exceeded: include `tenant_id`, `limit`, `operation: "rate_limit"` — use `get_logger(__name__)`
    - [x] 1.4.10 Log at DEBUG when request allowed: include `tenant_id`, `count`, `limit` — helps debugging without flooding INFO logs

- [x] Task 2: Register `RateLimiterMiddleware` in `app/main.py` (AC1, AC2)
  - [x] 2.1 Import `RateLimiterMiddleware` from `app.core.rate_limiter` at the top of `app/main.py`
  - [x] 2.2 In `create_app()`, add `application.add_middleware(RateLimiterMiddleware)` on the line **before** the existing `application.add_middleware(AuthMiddleware)` line
  - [x] 2.3 Final middleware registration order in `create_app()` (read carefully — see Dev Notes: Middleware Order):
    ```python
    application.add_middleware(RateLimiterMiddleware)  # added 1st → innermost → runs 3rd
    application.add_middleware(AuthMiddleware)          # added 2nd → middle → runs 2nd
    application.add_middleware(RequestIDMiddleware)     # added 3rd → outermost → runs 1st
    ```
  - [x] 2.4 Do NOT change `AuthMiddleware` or `RequestIDMiddleware` registrations

- [x] Task 3: Create ADR document (AC4)
  - [x] 3.1 Create `docs/adrs/007-rate-limiting.md` (check existing ADRs first; use next available number)
  - [x] 3.2 ADR must state: decision = in-process fixed window; rationale = v1 scale is 50 tenants, in-process sufficient; consequence = per-replica enforcement means N replicas allow up to N×limit; deferred = Redis-backed sliding window for v2

- [x] Task 4: Write tests (AC1, AC2, AC3)
  - [x] 4.1 Create `tests/core/test_rate_limiter.py`
  - [x] 4.2 Use a minimal test app fixture (see Dev Notes: Test Patterns) — avoids lifespan DB connections
  - [x] 4.3 Test: request below limit → handler returns 200
  - [x] 4.4 Test: (N+1)th request in same window → 429 with `{"error": {"code": "RATE_LIMIT_EXCEEDED", ...}}`
  - [x] 4.5 Test: expired window (manipulate `_counters` to inject a stale window_start) → counter resets, request passes through
  - [x] 4.6 Test: tenant with `rate_limit_rpm=0` or absent → falls back to `default_rate_limit_rpm` from config
  - [x] 4.7 Test: unauthenticated request (no `request.state.tenant`) → rate limiter skips, not 429 (auth handles it)
  - [x] 4.8 Test: two different tenants get independent counters — tenant A at limit does not block tenant B
  - [x] 4.9 Clear `_counters` between tests (fixture or monkeypatch) to prevent test pollution from module-level state
  - [x] 4.10 Run `ruff check app/ tests/` — must exit 0
  - [x] 4.11 Run `mypy app/ --strict` — must exit 0
  - [x] 4.12 Run `pytest tests/ -v` — all tests must pass (no regressions in existing 78+ tests)

### Review Findings

- [x] [Review][Decision] AC3 — `rate_limit_rpm: int = 60` Pydantic default masks absent MongoDB field; `settings.default_rate_limit_rpm` is never applied when field is absent from tenant document [app/models/tenant.py, app/core/rate_limiter.py] — fixed: changed to `int | None = None`, updated middleware condition to `is not None and > 0`, added `test_default_rate_limit_applied_when_rpm_none`
- [x] [Review][Patch] Trailing slash paths (e.g., `/v1/health/`) not in SKIP_AUTH_PATHS — fixed: normalize path with `rstrip("/")` before SKIP_AUTH_PATHS check [app/core/auth.py]
- [x] [Review][Patch] `TenantDocument.model_validate()` in AuthMiddleware can raise `ValidationError` — fixed: wrapped in try/except, returns 500 INTERNAL_SERVER_ERROR [app/core/auth.py]
- [x] [Review][Patch] MongoDB `find_one()` in AuthMiddleware can raise on network/timeout — fixed: wrapped in try/except, returns 503 PROVIDER_UNAVAILABLE [app/core/auth.py]
- [x] [Review][Patch] `real_app.state.motor_client` mutated without teardown — fixed: added `teardown_module()` to delete mock state [tests/core/test_exception_handlers.py]
- [x] [Review][Patch] `default_rate_limit_rpm` has no `gt=0` constraint — fixed: `Field(default=60, gt=0)` [app/core/config.py]
- [x] [Review][Defer] Cross-replica rate limiting: N replicas allow up to N×rpm per tenant per minute [app/core/rate_limiter.py] — deferred, per ADR 007 v2 scope
- [x] [Review][Defer] Fixed-window 2× boundary burst: up to 2× limit across window boundary [app/core/rate_limiter.py] — deferred, inherent fixed-window limitation, sliding window to v2
- [x] [Review][Defer] `_counters` unbounded growth: no eviction policy [app/core/rate_limiter.py] — deferred, negligible at v1 scale (≤50 tenants)
- [x] [Review][Defer] Auth timing oracle: missing key (no DB) vs invalid key (DB query) observable timing difference [app/core/auth.py] — deferred, architectural tradeoff

## Dev Notes

### Critical Architecture Rules (must not violate)

- **In-process fixed window only** — no Redis, no sliding window, no cross-replica synchronization; D7 explicitly defers Redis to v2
- **`RateLimiterMiddleware` runs AFTER `AuthMiddleware`** — it reads `request.state.tenant` which is set by `AuthMiddleware`; wrong middleware order causes `AttributeError`
- **Middleware returns `JSONResponse` directly for 429** — FastAPI exception handlers do not run for middleware responses; do NOT raise `RateLimitError` inside `RateLimiterMiddleware.dispatch`; return `JSONResponse` with error envelope manually
- **`_counters` is module-level mutable state** — this is intentional for in-process rate limiting; it persists across requests within the same process; tests MUST clear it between test cases
- **All logging via `get_logger(__name__)`** — never `print()`, never `import logging` directly
- **`RateLimitError` exception class exists** in `app/core/errors.py` — it is for service/handler code that needs to signal 429 programmatically; it is NOT raised in `RateLimiterMiddleware.dispatch`

### Middleware Order (critical — incorrect order breaks rate limiting)

Starlette's `add_middleware` inserts each middleware at position 0 of the middleware list. The stack is built by reversing the list before applying:

- **First `add_middleware` call = innermost** (processes requests last, closest to handlers)
- **Last `add_middleware` call = outermost** (processes requests first)

Required execution order: `RequestIDMiddleware → AuthMiddleware → RateLimiterMiddleware → handlers`

Reason: `RequestIDMiddleware` sets `request.state.request_id`, `AuthMiddleware` sets `request.state.tenant`, and `RateLimiterMiddleware` reads both. RateLimiterMiddleware must be innermost.

Current `create_app()` has:
```python
application.add_middleware(AuthMiddleware)        # existing — do NOT remove
application.add_middleware(RequestIDMiddleware)   # existing — do NOT remove
```

After this story, `create_app()` must be:
```python
application.add_middleware(RateLimiterMiddleware)  # NEW — added first → innermost → runs third
application.add_middleware(AuthMiddleware)          # existing → middle → runs second
application.add_middleware(RequestIDMiddleware)     # existing → outermost → runs first
```

### Existing State (do NOT recreate)

- `app/core/errors.py` — already has `RateLimitError(TrueRAGError)` with `http_status=429`, `code=ErrorCode.RATE_LIMIT_EXCEEDED`; also has `RATE_LIMIT_EXCEEDED` in `ErrorCode` enum — use these as-is
- `app/core/config.py` — already has `default_rate_limit_rpm: int = 60` — use `get_settings().default_rate_limit_rpm`
- `app/models/tenant.py` — already has `TenantDocument` with `rate_limit_rpm: int = 60` field — read this field in the middleware
- `app/core/auth.py` — already stores resolved `TenantDocument` at `request.state.tenant`; has `SKIP_AUTH_PATHS` for paths that bypass auth (and should bypass rate limiting too)
- `app/core/middleware.py` — already has `RequestIDMiddleware`; do NOT modify it
- `app/main.py` — already registers `AuthMiddleware` before `RequestIDMiddleware`; only ADD `RateLimiterMiddleware` registration and import
- `tests/core/` — `__init__.py` already exists; create `test_rate_limiter.py` in this directory

### Implementation: `app/core/rate_limiter.py`

```python
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.models.tenant import TenantDocument
from app.utils.observability import get_logger

logger = get_logger(__name__)

# Module-level fixed-window store: tenant_id → (window_start, request_count)
_counters: dict[str, tuple[float, int]] = {}


def _rate_limit_error(request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": str(ErrorCode.RATE_LIMIT_EXCEEDED),
                "message": "Rate limit exceeded",
                "request_id": request_id,
            }
        },
    )


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not hasattr(request.state, "tenant"):
            return await call_next(request)

        tenant: TenantDocument = request.state.tenant  # type: ignore[assignment]
        request_id: str = getattr(request.state, "request_id", "unknown")
        settings = get_settings()
        limit = tenant.rate_limit_rpm if tenant.rate_limit_rpm > 0 else settings.default_rate_limit_rpm

        now = time.monotonic()
        entry = _counters.get(tenant.tenant_id)

        if entry is None or (now - entry[0]) >= 60.0:
            _counters[tenant.tenant_id] = (now, 1)
            return await call_next(request)

        window_start, count = entry
        if count >= limit:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "operation": "rate_limit",
                    "extra_data": {"tenant_id": tenant.tenant_id, "limit": limit, "count": count},
                },
            )
            return _rate_limit_error(request_id)

        _counters[tenant.tenant_id] = (window_start, count + 1)
        return await call_next(request)
```

### Implementation: `app/main.py` change

Add ONE line before the existing `AuthMiddleware` registration:

```python
# After (add RateLimiterMiddleware line first):
application.add_middleware(RateLimiterMiddleware)  # innermost — runs after auth sets tenant
application.add_middleware(AuthMiddleware)          # middle — runs after request ID set
application.add_middleware(RequestIDMiddleware)     # outermost — runs first
```

Also add to imports: `from app.core.rate_limiter import RateLimiterMiddleware`

### mypy Strict Notes

- `request.state.tenant` is `Any` at the type level — use `# type: ignore[assignment]` when assigning to `TenantDocument`
- `_counters` is `dict[str, tuple[float, int]]` — fully typed, no issues
- `time.monotonic()` returns `float` — no annotation needed, inferred correctly
- Return type of `dispatch` must be annotated as `Response` — already in the signature
- Import `Any` from `typing` is NOT needed here — use specific types throughout

### Test Patterns

```python
# tests/core/test_rate_limiter.py

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core import rate_limiter as rl_module
from app.models.tenant import TenantDocument


_FAKE_TENANT = TenantDocument(
    tenant_id="test-tenant",
    api_key_hash="fake-hash",
    rate_limit_rpm=2,  # low limit for easy testing
    created_at=datetime.now(UTC),
)


@pytest.fixture(autouse=True)
def clear_counters() -> None:
    """Reset module-level state between tests."""
    rl_module._counters.clear()


@pytest.fixture
def rate_limit_app() -> FastAPI:
    from app.core.auth import AuthMiddleware
    from app.core.middleware import RequestIDMiddleware
    from app.core.rate_limiter import RateLimiterMiddleware

    mini_app = FastAPI()

    @mini_app.get("/protected")
    async def protected_route() -> JSONResponse:
        return JSONResponse({"ok": True})

    @mini_app.get("/v1/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    mini_app.add_middleware(RateLimiterMiddleware)
    mini_app.add_middleware(AuthMiddleware)
    mini_app.add_middleware(RequestIDMiddleware)

    # Mock motor_client — returns _FAKE_TENANT on find_one
    from unittest.mock import AsyncMock
    raw_key = "test-api-key"
    import hashlib
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    tenant_doc = {
        "tenant_id": _FAKE_TENANT.tenant_id,
        "api_key_hash": key_hash,
        "rate_limit_rpm": _FAKE_TENANT.rate_limit_rpm,
        "created_at": _FAKE_TENANT.created_at,
    }
    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=tenant_doc)
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    mini_app.state.motor_client = mock_motor

    return mini_app


@pytest.mark.asyncio
async def test_below_limit_passes(rate_limit_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_over_limit_returns_429(rate_limit_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        for _ in range(_FAKE_TENANT.rate_limit_rpm):
            await client.get("/protected", headers={"X-API-Key": "test-api-key"})
        response = await client.get("/protected", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_health_not_rate_limited(rate_limit_app: FastAPI) -> None:
    # Health endpoint skips auth AND rate limiting
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        for _ in range(10):  # well over limit
            response = await client.get("/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_expired_window_resets_counter(rate_limit_app: FastAPI) -> None:
    # Inject a stale window directly into _counters
    rl_module._counters["test-tenant"] = (time.monotonic() - 61.0, 999)
    async with AsyncClient(
        transport=ASGITransport(app=rate_limit_app), base_url="http://test"
    ) as client:
        response = await client.get("/protected", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
```

**Counter isolation between tests:** The `autouse=True` fixture calls `rl_module._counters.clear()` before each test — critical to prevent cross-test pollution from module-level state.

### ADR Format

Create `docs/adrs/007-rate-limiting.md` with at minimum:
- **Status:** Accepted
- **Context:** v1 supports 50 tenants; in-process enforcement is sufficient; Redis adds infrastructure complexity
- **Decision:** In-process fixed-window counter per tenant per minute; each ECS Fargate replica enforces independently
- **Consequences:** With N replicas, a tenant may receive up to N×rpm requests before being limited. Acceptable for v1 scale.
- **Deferred:** Redis-backed sliding window counter (global, cross-replica) deferred to v2

### Anti-Patterns to Avoid

- **Do NOT use `asyncio.Lock`** for `_counters` — the GIL protects dict operations in CPython; adding an async lock creates await points inside middleware and slows every request
- **Do NOT use `time.time()`** for the window clock — use `time.monotonic()` which is immune to NTP adjustments and system clock changes
- **Do NOT raise `RateLimitError` inside `RateLimiterMiddleware.dispatch`** — FastAPI exception handlers don't catch middleware exceptions; return `JSONResponse` directly for 429
- **Do NOT skip rate limiting for auth failures** — when `request.state.tenant` is not set, skip rate limiting (auth middleware handles the 401 on its own)
- **Do NOT create `app/core/dependencies.py`** — that is Story 1.8
- **Do NOT create `app/providers/registry.py`** — that is Story 1.8
- **Do NOT add any routes** — this story is middleware only
- **Do NOT use Redis** — deferred to v2 per architecture decision D7
- **Do NOT implement sliding window** — fixed window is the v1 decision

### File Locations

```
app/core/rate_limiter.py        ← NEW: RateLimiterMiddleware + fixed-window store
app/main.py                     ← MODIFIED: add RateLimiterMiddleware registration + import
docs/adrs/007-rate-limiting.md  ← NEW: ADR documenting per-replica enforcement + v2 deferral
tests/core/test_rate_limiter.py ← NEW: rate limiter tests
```

### Dependencies Already in requirements.txt

No new dependencies needed. All required packages are already present:
- `fastapi` / `starlette` — `BaseHTTPMiddleware`, `Request`, `JSONResponse`
- `time` — standard library (`monotonic`, always available)
- `pydantic` — `TenantDocument` from `app/models/tenant.py`

### Previous Story Learnings (from Story 1.6)

- **Middleware returns `JSONResponse` directly** — never raise exceptions inside `dispatch`; exception handlers do not run for middleware responses
- **Starlette `add_middleware` is LIFO** — first-added = innermost = runs last before handlers; this is critical for RateLimiterMiddleware which must be innermost (added first in `create_app()`)
- **`request.state` is `Any`** — always annotate reads with `# type: ignore` or explicit cast
- **Mock `motor_client` at `app.state.motor_client`** — not at the motor library level; mock the attribute on `mini_app.state`
- **`autouse=True` fixture for module-level cleanup** — `_counters` is module-level state; always clear it between tests to prevent pollution
- **Use `from datetime import UTC`** (Python 3.11+) — `datetime.now(UTC)` is cleaner than `datetime.now(datetime.timezone.UTC)`; Story 1.6 tests use this pattern
- **`from collections.abc import ...`** not `from typing import ...` for `Callable`, `Generator`, etc. (ruff UP035)
- **Import order for ruff I001:** stdlib → third-party → first-party (`app.*`) with blank lines between groups

### References

- [Source: architecture.md#D7] — Rate limiting: in-process fixed window per tenant per minute; Redis-backed sliding window deferred to v2
- [Source: architecture.md#Authentication & Security] — FR52: per-tenant per-minute request rate limits configurable per tenant
- [Source: architecture.md#app/core/rate_limiter.py] — "FR52: per-tenant fixed window counter"
- [Source: architecture.md#Enforcement Guidelines] — All agents MUST use structured logger from `app/utils/observability.py`
- [Source: architecture.md#D10] — Error envelope: `{"error": {"code": ..., "message": ..., "request_id": ...}}`
- [Source: architecture.md#D15] — Structured logging: all log calls include `operation`, `tenant_id`, `request_id`
- [Source: epics.md#Story 1.7] — User story and 4 acceptance criteria
- [Source: story 1.6 dev notes] — Middleware order is LIFO; `add_middleware` inserts at position 0

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- ruff E501: `limit = ...` line exceeded 100 chars — wrapped with parentheses
- ruff I001: import order in `app/main.py` — sorted `rate_limiter` import alphabetically after `exception_handlers`
- mypy unused-ignore: `# type: ignore[assignment]` on `tenant: TenantDocument = request.state.tenant` was unnecessary (mypy inferred correctly) — removed

### Completion Notes List

- Created `app/core/rate_limiter.py` with `RateLimiterMiddleware(BaseHTTPMiddleware)` implementing in-process fixed-window rate limiting per tenant per minute using `time.monotonic()`
- Module-level `_counters: dict[str, tuple[float, int]]` stores `(window_start, count)` per `tenant_id`
- Returns `JSONResponse` with HTTP 429 and `ErrorCode.RATE_LIMIT_EXCEEDED` directly from middleware (no exception raised)
- Skips rate limiting when `request.state.tenant` is absent (unauthenticated/health paths)
- Falls back to `settings.default_rate_limit_rpm` when tenant's `rate_limit_rpm == 0`
- Registered in `create_app()` as innermost middleware (added first), correctly after `AuthMiddleware` sets `request.state.tenant`
- Created `docs/adrs/007-rate-limiting.md` documenting in-process enforcement, per-replica behaviour, and Redis deferral to v2
- 7 new tests in `tests/core/test_rate_limiter.py`; all 85 tests pass (78 existing + 7 new); ruff clean; mypy strict clean

### File List

- `app/core/rate_limiter.py` (new)
- `app/main.py` (modified)
- `docs/adrs/007-rate-limiting.md` (new)
- `tests/core/test_rate_limiter.py` (new)

## Change Log

- 2026-04-20: Implemented in-process fixed-window rate limiter middleware, registered in app, added ADR 007, and 7 tests covering all ACs (Date: 2026-04-20)
