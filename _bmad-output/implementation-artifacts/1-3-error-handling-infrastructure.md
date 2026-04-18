# Story 1.3: Error Handling Infrastructure

Status: done

## Story

As an AI Platform Engineer,
I want a centralised error system with typed exceptions, an `ErrorCode` enum, and a consistent error response envelope,
So that every API error returns a predictable `{"error": {"code": "...", "message": "...", "request_id": "..."}}` structure callers can rely on.

## Acceptance Criteria

**AC1:** Given `app/core/errors.py`
When inspected
Then it contains: `TrueRAGError` base exception with typed subclasses (`NamespaceViolationError`, `PIIDetectedError`, `ProviderUnavailableError`, `IngestionError`, `RateLimitError`); `ErrorCode` enum containing at minimum `AGENT_NOT_FOUND`, `NAMESPACE_VIOLATION`, `PII_DETECTED`, `CHUNKING_STRATEGY_MISMATCH`, `EMBEDDING_MODEL_MISMATCH`, `REINDEX_REQUIRED`, `RATE_LIMIT_EXCEEDED`; no error code is hardcoded as a raw string anywhere in the codebase

**AC2:** Given a `TrueRAGError` subclass is raised in any handler
When `app/core/exception_handlers.py` processes it
Then the response body is `{"error": {"code": "...", "message": "...", "request_id": "..."}}` with the appropriate HTTP status code; no FastAPI default `detail` field leaks through

**AC3:** Given `ProviderUnavailableError` is raised
When the exception handler processes it
Then the HTTP response is exactly 503 Service Unavailable with the error envelope

## Tasks / Subtasks

- [x] Task 1: Create `app/core/errors.py` (AC: 1)
  - [x] 1.1 Define `ErrorCode(str, Enum)` with values: `AGENT_NOT_FOUND`, `NAMESPACE_VIOLATION`, `PII_DETECTED`, `CHUNKING_STRATEGY_MISMATCH`, `EMBEDDING_MODEL_MISMATCH`, `REINDEX_REQUIRED`, `RATE_LIMIT_EXCEEDED` — each value equals its own name (e.g. `AGENT_NOT_FOUND = "AGENT_NOT_FOUND"`)
  - [x] 1.2 Define `TrueRAGError(Exception)` base class with constructor `__init__(self, code: ErrorCode, message: str, http_status: int = 500)` storing all three as instance attributes
  - [x] 1.3 Define typed subclasses with fixed `http_status` defaults:
    - `NamespaceViolationError(TrueRAGError)` — default `http_status=403`, default `code=ErrorCode.NAMESPACE_VIOLATION`
    - `PIIDetectedError(TrueRAGError)` — default `http_status=422`, default `code=ErrorCode.PII_DETECTED`
    - `ProviderUnavailableError(TrueRAGError)` — default `http_status=503`, default `code=ErrorCode.PROVIDER_UNAVAILABLE` (add `PROVIDER_UNAVAILABLE` to enum)
    - `IngestionError(TrueRAGError)` — default `http_status=500`, default `code=ErrorCode.INGESTION_ERROR` (add `INGESTION_ERROR` to enum)
    - `RateLimitError(TrueRAGError)` — default `http_status=429`, default `code=ErrorCode.RATE_LIMIT_EXCEEDED`
  - [x] 1.4 Each subclass constructor accepts optional `message: str` and optionally overrides `code`/`http_status` — subclasses call `super().__init__(code=..., message=message, http_status=...)`

- [x] Task 2: Create `app/core/exception_handlers.py` (AC: 2, 3)
  - [x] 2.1 Import `Request` from `fastapi`, `JSONResponse` from `fastapi.responses`, `TrueRAGError` from `app/core/errors`
  - [x] 2.2 Implement `async def truerag_exception_handler(request: Request, exc: TrueRAGError) -> JSONResponse`: reads `request_id` from `request.state.request_id` (falls back to `"unknown"` if not set); returns `JSONResponse(status_code=exc.http_status, content={"error": {"code": exc.code.value, "message": exc.message, "request_id": request_id}})`
  - [x] 2.3 Implement `async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse`: returns HTTP 500 with envelope `{"error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred", "request_id": request_id}}` — add `INTERNAL_SERVER_ERROR` to `ErrorCode` enum; logs the exception via `get_logger(__name__).error(...)` with `operation="unhandled_exception"` and `extra={"operation": "unhandled_exception"}`
  - [x] 2.4 Export both handlers from module

- [x] Task 3: Register exception handlers in `app/main.py` (AC: 2, 3)
  - [x] 3.1 Import `truerag_exception_handler`, `generic_exception_handler` from `app/core/exception_handlers`
  - [x] 3.2 Import `TrueRAGError` from `app/core/errors`
  - [x] 3.3 In `create_app()`, after `application.add_middleware(RequestIDMiddleware)`, register:
    - `application.add_exception_handler(TrueRAGError, truerag_exception_handler)`
    - `application.add_exception_handler(Exception, generic_exception_handler)`
  - [x] 3.4 Handler registration order: `TrueRAGError` before `Exception` — FastAPI matches most-specific first

- [x] Task 4: Write tests (AC: 1, 2, 3)
  - [x] 4.1 Create `tests/core/test_errors.py`:
    - Test `ErrorCode` enum has all required values: `AGENT_NOT_FOUND`, `NAMESPACE_VIOLATION`, `PII_DETECTED`, `CHUNKING_STRATEGY_MISMATCH`, `EMBEDDING_MODEL_MISMATCH`, `REINDEX_REQUIRED`, `RATE_LIMIT_EXCEEDED`
    - Test `TrueRAGError` stores `code`, `message`, `http_status`
    - Test `ProviderUnavailableError` default `http_status` is 503
    - Test `RateLimitError` default `http_status` is 429
    - Test `NamespaceViolationError` default `http_status` is 403
    - Test each subclass is a subclass of `TrueRAGError`
  - [x] 4.2 Create `tests/core/test_exception_handlers.py` using `TestClient` from `fastapi.testclient`:
    - Add a temporary test route to the test FastAPI app that raises `ProviderUnavailableError("test message")` — assert response status is 503, body has `{"error": {"code": "PROVIDER_UNAVAILABLE", "message": "test message", "request_id": ...}}`, no `detail` key in body
    - Add a test route that raises `NamespaceViolationError("namespace test")` — assert 403
    - Add a test route that raises `RateLimitError("rate test")` — assert 429
    - Add a test route that raises a plain `RuntimeError` — assert 500, body follows error envelope format
    - Test that `request_id` in response body is a non-empty string (UUID format from `RequestIDMiddleware`)
  - [x] 4.3 Run `ruff check app/ tests/` — must exit 0
  - [x] 4.4 Run `mypy app/ --strict` — must exit 0
  - [x] 4.5 Run `pytest tests/ -v` — all tests must pass

## Dev Notes

### Critical Architecture Rules (must not violate)

- **`app/core/errors.py` is the ONLY place error codes are defined** — `ErrorCode` enum, never inline strings. Every future story must import from here.
- **No raw `HTTPException` in business logic** — `TrueRAGError` subclasses only in services/pipelines/providers; `HTTPException` may only appear in API layer handlers (Stories 1.6+).
- **`app/utils/observability.py` is still the ONLY file that imports `logging`** — `exception_handlers.py` uses `get_logger(__name__)` from observability, never `import logging` directly.
- **Error envelope shape is immutable** — `{"error": {"code": str, "message": str, "request_id": str}}` — no `detail` key, no `status` key, no wrapper nesting.
- **`request_id` always comes from `request.state.request_id`** — set by `RequestIDMiddleware` from Story 1.2 before any handler runs. If somehow absent, fall back to `"unknown"` to avoid a secondary error.

### File Locations

```
app/core/errors.py                  ← NEW: ErrorCode enum + TrueRAGError hierarchy
app/core/exception_handlers.py      ← NEW: maps typed exceptions → standard error envelope
app/main.py                         ← MODIFY: register exception handlers in create_app()
tests/core/test_errors.py           ← NEW: unit tests for error types
tests/core/test_exception_handlers.py ← NEW: integration tests via TestClient
```

### Exception Hierarchy Reference

```python
# app/core/errors.py

from enum import Enum

class ErrorCode(str, Enum):
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    NAMESPACE_VIOLATION = "NAMESPACE_VIOLATION"
    PII_DETECTED = "PII_DETECTED"
    CHUNKING_STRATEGY_MISMATCH = "CHUNKING_STRATEGY_MISMATCH"
    EMBEDDING_MODEL_MISMATCH = "EMBEDDING_MODEL_MISMATCH"
    REINDEX_REQUIRED = "REINDEX_REQUIRED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INGESTION_ERROR = "INGESTION_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"

class TrueRAGError(Exception):
    def __init__(self, code: ErrorCode, message: str, http_status: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

class NamespaceViolationError(TrueRAGError):
    def __init__(self, message: str = "Namespace violation") -> None:
        super().__init__(code=ErrorCode.NAMESPACE_VIOLATION, message=message, http_status=403)

class PIIDetectedError(TrueRAGError):
    def __init__(self, message: str = "PII detected in input") -> None:
        super().__init__(code=ErrorCode.PII_DETECTED, message=message, http_status=422)

class ProviderUnavailableError(TrueRAGError):
    def __init__(self, message: str = "Provider unavailable") -> None:
        super().__init__(code=ErrorCode.PROVIDER_UNAVAILABLE, message=message, http_status=503)

class IngestionError(TrueRAGError):
    def __init__(self, message: str = "Ingestion failed") -> None:
        super().__init__(code=ErrorCode.INGESTION_ERROR, message=message, http_status=500)

class RateLimitError(TrueRAGError):
    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(code=ErrorCode.RATE_LIMIT_EXCEEDED, message=message, http_status=429)
```

### Exception Handler Pattern

```python
# app/core/exception_handlers.py

from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.errors import ErrorCode, TrueRAGError
from app.utils.observability import get_logger

logger = get_logger(__name__)

async def truerag_exception_handler(request: Request, exc: TrueRAGError) -> JSONResponse:
    request_id: str = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code.value, "message": exc.message, "request_id": request_id}},
    )

async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id: str = getattr(request.state, "request_id", "unknown")
    logger.error("unhandled_exception", extra={"operation": "unhandled_exception", "extra": {"error": str(exc)}})
    return JSONResponse(
        status_code=500,
        content={"error": {"code": ErrorCode.INTERNAL_SERVER_ERROR.value, "message": "An unexpected error occurred", "request_id": request_id}},
    )
```

### Registration in `app/main.py`

```python
# In create_app(), add after add_middleware:
application.add_exception_handler(TrueRAGError, truerag_exception_handler)  # type: ignore[arg-type]
application.add_exception_handler(Exception, generic_exception_handler)
```

Note: FastAPI's `add_exception_handler` type stubs expect `type[Exception]` not `type[TrueRAGError]` directly — use `# type: ignore[arg-type]` for mypy strict compliance. This is a known FastAPI/starlette typing limitation.

### Test Pattern for Exception Handler Tests

```python
# tests/core/test_exception_handlers.py
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.errors import ProviderUnavailableError
from app.core.exception_handlers import truerag_exception_handler, generic_exception_handler

def make_test_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_exception_handler(ProviderUnavailableError, truerag_exception_handler)  # type: ignore[arg-type]
    # add test routes here
    return test_app
```

Use `TestClient` from `fastapi.testclient` — this is the synchronous test client (uses `httpx` internally). Preferred over `AsyncClient` for simple handler tests.

### HTTP Status Mapping (authoritative)

| Exception | HTTP Status | ErrorCode |
|---|---|---|
| `NamespaceViolationError` | 403 | `NAMESPACE_VIOLATION` |
| `PIIDetectedError` | 422 | `PII_DETECTED` |
| `ProviderUnavailableError` | 503 | `PROVIDER_UNAVAILABLE` |
| `IngestionError` | 500 | `INGESTION_ERROR` |
| `RateLimitError` | 429 | `RATE_LIMIT_EXCEEDED` |
| `TrueRAGError` (base) | 500 | caller-supplied |
| `Exception` (generic) | 500 | `INTERNAL_SERVER_ERROR` |

### Previous Story Learnings (from Story 1.2)

- **`tests/core/` already exists** (created in Story 1.2 with `__init__.py`) — do NOT recreate, just add new test files alongside
- **`app/core/__init__.py` already exists** — do NOT recreate, just add `errors.py` and `exception_handlers.py` alongside
- **Ruff UP035:** use `from collections.abc import Callable` not `from typing import Callable`; same for `Generator`, `AsyncGenerator`, `Awaitable`
- **Import order for ruff I001:** stdlib → third-party → first-party (`app.*`) — blank line between groups
- **`from datetime import UTC`** not `from datetime import timezone; timezone.UTC` (Python 3.11 uses module-level `UTC`)
- **`uv venv .venv --python 3.11` + `uv pip install -r requirements-dev.txt`** — use for any new environment setup
- **mypy strict requires explicit type annotations** — handler functions must annotate all params and return type
- **`BaseHTTPMiddleware` call_next typing** — use `RequestResponseEndpoint` from `starlette.middleware.base`

### Anti-Patterns to Avoid

- **Do NOT** hardcode error code strings inline anywhere — always `ErrorCode.SOME_CODE.value`
- **Do NOT** raise `HTTPException` from `app/services/`, `app/pipelines/`, or `app/providers/` — only `TrueRAGError` subclasses
- **Do NOT** let the `detail` key appear in any error response — FastAPI's default `HTTPException` handler produces `{"detail": "..."}`, which is the exact shape this story replaces
- **Do NOT** `import logging` in `exception_handlers.py` — use `get_logger(__name__)` from `app/utils/observability`
- **Do NOT** create `app/core/auth.py` or `app/core/rate_limiter.py` — those are Stories 1.6 and 1.7
- **Do NOT** create `app/utils/secrets.py` — that's Story 1.5
- **Do NOT** add connection logic — that's Story 1.4
- **Do NOT** catch `TrueRAGError` in `generic_exception_handler` — FastAPI routes specific handlers before fallback; the generic handler only fires for non-`TrueRAGError` exceptions

### References

- [Source: architecture.md#D10] — Error response envelope shape: `{"error": {"code": ..., "message": ..., "request_id": ...}}`
- [Source: architecture.md#Communication Patterns#Pipeline Stage Error Handling] — Exception hierarchy and "no raw HTTPException in business logic" rule
- [Source: architecture.md#Enforcement Guidelines] — `app/core/errors.py` is canonical error code location
- [Source: architecture.md#Project Structure] — `app/core/errors.py`, `app/core/exception_handlers.py` file locations
- [Source: epics.md#Story 1.3] — User story and 3 acceptance criteria

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Completion Notes List

- Created `app/core/errors.py` with `ErrorCode(StrEnum)` (10 codes) and full `TrueRAGError` hierarchy (5 subclasses)
- Created `app/core/exception_handlers.py` with `truerag_exception_handler` (typed errors → JSON envelope) and `generic_exception_handler` (fallback 500, logs via observability)
- Modified `app/main.py`: registered both handlers in `create_app()` after `RequestIDMiddleware`, `TrueRAGError` before `Exception`
- Created `tests/core/test_errors.py`: 11 unit tests covering enum values, attribute storage, all subclass defaults, parametrized subclass-of check
- Created `tests/core/test_exception_handlers.py`: 7 integration tests via `TestClient` — 503/403/429/500 status codes, envelope shape, UUID `request_id`, no `detail` key
- All 44 tests pass; ruff and mypy --strict exit 0
- Note: used `StrEnum` (Python 3.11) per ruff UP042 — `(str, Enum)` pattern is deprecated
- Post-review fixes: subclass constructors now accept optional `code`/`http_status` overrides (Task 1.4); logger uses `extra_data` key to match `JSONFormatter.format()`; added two real-app wiring tests via `app.main.app`

### File List

- app/core/errors.py (new)
- app/core/exception_handlers.py (new)
- app/main.py (modified)
- tests/core/test_errors.py (new)
- tests/core/test_exception_handlers.py (new)

## Change Log

- 2026-04-18: Story 1.3 created — error handling infrastructure, `ErrorCode` enum, `TrueRAGError` hierarchy, `exception_handlers.py`, registration in `main.py`, tests (claude-sonnet-4-6)
- 2026-04-18: Story 1.3 implemented — all tasks complete, 39 tests pass, ruff + mypy --strict clean (claude-sonnet-4-6)
