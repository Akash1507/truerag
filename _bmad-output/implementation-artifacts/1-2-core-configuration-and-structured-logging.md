# Story 1.2: Core Configuration & Structured Logging

Status: review

## Story

As an AI Platform Engineer,
I want a typed settings system and structured JSON logger wired into the application,
so that all configuration is validated at startup and every log entry is a consistent, CloudWatch-queryable JSON object.

## Acceptance Criteria

**AC1:** Given `app/core/config.py` loaded by `pydantic-settings`, when the application starts, then all required settings are type-validated; missing required settings cause a startup error naming the setting; no secrets (credentials, connection strings, API keys) appear in the Settings class values or `.env` files.

**AC2:** Given a request enters the API, when any handler executes, then a unique UUID v4 `request_id` is generated at middleware entry, injected into request context via `contextvars`, and included in every log entry emitted during that request lifecycle.

**AC3:** Given the structured logger in `app/utils/observability.py`, when a log is emitted at any level, then the output is a valid JSON object on stdout with exactly these fields: `timestamp` (ISO 8601 UTC), `level`, `tenant_id`, `agent_id`, `request_id`, `operation`, `latency_ms`, `extra` — never plain text, never via `print()`, never via `import logging` directly in any module other than `observability.py`.

## Tasks / Subtasks

- [x] Task 1: Create `app/core/config.py` with pydantic-settings Settings class (AC: 1)
  - [x] 1.1 Define `Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)`
  - [x] 1.2 Add non-secret fields: `app_env: str = "local"`, `log_level: str = "INFO"`, `aws_region: str = "us-east-1"`, `default_rate_limit_rpm: int = 60`
  - [x] 1.3 Add secret-name fields (NOT secrets themselves — just the Secrets Manager path strings): `mongodb_secret_name: str = "truerag/mongodb/uri"`, `pgvector_secret_name: str = "truerag/pgvector/dsn"` — these are read by `app/utils/secrets.py` (Story 1.5)
  - [x] 1.4 Add `@lru_cache` singleton getter: `def get_settings() -> Settings: return Settings()`
  - [x] 1.5 Validate `log_level` is one of `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` using a `@field_validator`
  - [x] 1.6 Update `.env.example` to add `DEFAULT_RATE_LIMIT_RPM=60` with inline comment; confirm existing `LOG_LEVEL`, `AWS_REGION`, `APP_ENV` match field names

- [x] Task 2: Create `app/utils/observability.py` with structured logger and latency tracker (AC: 2, 3)
  - [x] 2.1 Define `contextvars.ContextVar` module-level variables: `_request_id_var`, `_tenant_id_var`, `_agent_id_var` — typed as `ContextVar[str]` / `ContextVar[str | None]` with appropriate defaults
  - [x] 2.2 Expose `set_request_context(request_id, tenant_id, agent_id)` function that sets all three context vars; returns tokens for cleanup
  - [x] 2.3 Implement `JSONFormatter(logging.Formatter)` that overrides `format(record)` to produce the D15 JSON schema: `{"timestamp": ISO8601, "level": str, "tenant_id": str|null, "agent_id": str|null, "request_id": str, "operation": str, "latency_ms": int|null, "extra": dict}` — reads `request_id`, `tenant_id`, `agent_id` from `contextvars` if not set on the record; reads `operation`, `latency_ms`, `extra_data` from `record` attributes via `getattr(record, field, default)` — never raises, only logs safely
  - [x] 2.4 Implement `get_logger(name: str) -> logging.Logger`: creates/retrieves a `logging.Logger`, attaches `JSONFormatter` on a `StreamHandler(sys.stdout)` if no handlers, sets level from `get_settings().log_level`; sets `logger.propagate = False` to prevent double output
  - [x] 2.5 Implement `LatencyTracker` dataclass: `__init__` records `time.perf_counter()` start; `elapsed_ms() -> int` returns elapsed milliseconds; used as `tracker = LatencyTracker(); ... logger.info("msg", extra={"operation": "op", "latency_ms": tracker.elapsed_ms()})`
  - [x] 2.6 Export from module: `get_logger`, `set_request_context`, `LatencyTracker`

- [x] Task 3: Add `RequestIDMiddleware` to `app/main.py` (AC: 2)
  - [x] 3.1 Implement `RequestIDMiddleware(BaseHTTPMiddleware)` in `app/core/middleware.py` (new file): generates `str(uuid.uuid4())`, calls `set_request_context(request_id=..., tenant_id=None, agent_id=None)`, stores result on `request.state.request_id`, calls `call_next(request)`, adds `X-Request-ID` response header
  - [x] 3.2 Register middleware in `create_app()` in `app/main.py`: `application.add_middleware(RequestIDMiddleware)` — added BEFORE the router is included; order matters (middleware wraps handlers)
  - [x] 3.3 Add module-level logger in `app/main.py` using `get_logger(__name__)` and log an INFO entry `operation="app_startup"` inside the lifespan on startup

- [x] Task 4: Wire structured logger into the existing health endpoint (AC: 3)
  - [x] 4.1 In `app/api/v1/observability.py`, import `get_logger` from `app/utils/observability.py` and create a module-level logger: `logger = get_logger(__name__)`
  - [x] 4.2 Add an INFO log in the health endpoint handler: `logger.info("health_check", extra={"operation": "health_check"})` — this validates the logger end-to-end through a real request path

- [x] Task 5: Write tests (AC: 1, 2, 3)
  - [x] 5.1 Create `tests/core/test_config.py`: test that `Settings()` loads from env; test that missing a required field raises `ValidationError` (use monkeypatch to unset env var); test that invalid `log_level` value raises `ValidationError`; test `get_settings()` returns same instance (singleton)
  - [x] 5.2 Create `tests/utils/test_observability.py`: test `get_logger()` returns a logger with a `StreamHandler`; test `JSONFormatter.format()` produces valid JSON with all 8 required fields; test that `request_id` from `set_request_context()` appears in log output; test `LatencyTracker.elapsed_ms()` returns a non-negative integer
  - [x] 5.3 Create `tests/core/test_middleware.py`: test that a request to any endpoint (e.g., `GET /docs`) includes `X-Request-ID` header in response; test that `request_id` in the header is a valid UUID v4
  - [x] 5.4 Run `ruff check app/ tests/` and `mypy app/ --strict` — both must exit 0
  - [x] 5.5 Run `pytest tests/ -v` — all tests must pass

## Dev Notes

### Critical Architecture Rules (must not violate)

- **`app/utils/observability.py` is the ONLY file that imports `logging`** — every other module calls `get_logger(__name__)` from `app/utils/observability.py`. Enforce this in code review. Violation breaks the structured log guarantee.
- **No secrets in Settings** — `Settings` class stores only non-secret config (log level, env name, region) and Secrets Manager path strings. The actual credentials are fetched at operation time by `app/utils/secrets.py` (Story 1.5). Adding a `MONGODB_URI` field directly to Settings violates D8 / the "no credentials in env" rule.
- **`datetime.now(timezone.UTC)` exclusively** — `datetime.utcnow()` is deprecated in Python 3.12 and returns a naive datetime. Import: `from datetime import datetime, timezone`. Use: `datetime.now(timezone.UTC).isoformat()`.
- **No routes in `main.py`** — RequestIDMiddleware goes there but routes stay in `app/api/v1/` routers.
- **`BaseHTTPMiddleware` call_next typing** — mypy strict requires explicit type annotation: `from starlette.types import ASGIApp`; the `dispatch` signature is `async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response` where `RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]`.

### Settings Class — Field Reference

```python
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Non-secret app config
    app_env: str = "local"
    log_level: str = "INFO"
    aws_region: str = "us-east-1"
    default_rate_limit_rpm: int = 60

    # Secrets Manager path references (NOT the actual secrets)
    mongodb_secret_name: str = "truerag/mongodb/uri"
    pgvector_secret_name: str = "truerag/pgvector/dsn"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return v.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### Structured Logger — Implementation Pattern

```python
# app/utils/observability.py
import json
import logging
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_agent_id_var: ContextVar[str | None] = ContextVar("agent_id", default=None)


def set_request_context(
    *,
    request_id: str,
    tenant_id: str | None = None,
    agent_id: str | None = None,
) -> None:
    _request_id_var.set(request_id)
    _tenant_id_var.set(tenant_id)
    _agent_id_var.set(agent_id)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.UTC).isoformat(),
            "level": record.levelname,
            "tenant_id": getattr(record, "tenant_id", None) or _tenant_id_var.get(),
            "agent_id": getattr(record, "agent_id", None) or _agent_id_var.get(),
            "request_id": getattr(record, "request_id", None) or _request_id_var.get(),
            "operation": getattr(record, "operation", ""),
            "latency_ms": getattr(record, "latency_ms", None),
            "extra": getattr(record, "extra_data", {}),
        }
        return json.dumps(entry)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(getattr(logging, get_settings().log_level, logging.INFO))
    return logger


class LatencyTracker:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)
```

**How callers use the logger:**
```python
# In any module other than observability.py:
from app.utils.observability import get_logger, LatencyTracker

logger = get_logger(__name__)

tracker = LatencyTracker()
# ... do work ...
logger.info("msg", extra={"operation": "my_op", "latency_ms": tracker.elapsed_ms()})
```

**NEVER do this in any module other than observability.py:**
```python
import logging  # FORBIDDEN in other modules
print("something")  # FORBIDDEN everywhere
```

### RequestIDMiddleware — Implementation Pattern

```python
# app/core/middleware.py
import uuid
from collections.abc import Callable, Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.utils.observability import set_request_context


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = str(uuid.uuid4())
        set_request_context(request_id=request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

**Note on mypy strict:** `BaseHTTPMiddleware.dispatch` has `call_next` typed as `RequestResponseEndpoint` in starlette's type stubs. You may need to import `from starlette.middleware.base import RequestResponseEndpoint` and use it instead of the manual `Callable` alias if mypy complains. The `Callable[[Request], Awaitable[Response]]` form may not satisfy the stub exactly.

### File Structure for This Story

New files to create:
```
app/core/config.py          ← Settings class + get_settings()
app/core/middleware.py      ← RequestIDMiddleware
app/utils/observability.py  ← JSONFormatter, get_logger, set_request_context, LatencyTracker
tests/core/__init__.py      ← new package (already exists from 1.1? confirm)
tests/core/test_config.py
tests/core/test_middleware.py
tests/utils/test_observability.py
```

Files to modify:
```
app/main.py                 ← add middleware registration + startup log
app/api/v1/observability.py ← add logger import + log call in health handler
.env.example                ← add DEFAULT_RATE_LIMIT_RPM=60
```

**Check before creating:** `tests/core/` directory — Story 1.1 created `tests/` subdirectories mirroring `app/`. The architecture spec includes `app/core/` but it's unclear if `tests/core/` was in the 1.1 directory list. Verify with `ls tests/` first; if `tests/core/` doesn't exist, create it with `__init__.py`.

### Mypy Strict Compliance Notes

- `ContextVar` needs explicit type parameter: `ContextVar[str]`, `ContextVar[str | None]`
- `dict[str, Any]` requires `from typing import Any`
- `json.dumps` return value is `str` — no annotation needed
- `getattr(record, "operation", "")` returns `Any` in mypy — cast if needed: `str(getattr(record, "operation", ""))`
- `@lru_cache` on `get_settings()` must have `()` call signature (no args) — this is correct
- `@field_validator` requires `@classmethod` decorator in pydantic v2
- `logging.Logger` is the correct return type for `get_logger()`
- `time.perf_counter()` returns `float` — `int(...)` converts correctly

### Testing Pattern

```python
# tests/utils/test_observability.py
import json
import logging
import pytest
from app.utils.observability import get_logger, set_request_context, LatencyTracker, JSONFormatter


def test_json_formatter_produces_valid_json() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="test message", args=(), exc_info=None
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    required_fields = {"timestamp", "level", "tenant_id", "agent_id", "request_id", "operation", "latency_ms", "extra"}
    assert required_fields == set(parsed.keys())


def test_request_id_propagates_to_log() -> None:
    set_request_context(request_id="test-uuid-1234")
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="test", args=(), exc_info=None
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["request_id"] == "test-uuid-1234"


def test_latency_tracker_returns_nonnegative() -> None:
    tracker = LatencyTracker()
    assert tracker.elapsed_ms() >= 0
```

```python
# tests/core/test_config.py
import pytest
from pydantic import ValidationError
from app.core.config import Settings


def test_invalid_log_level_raises() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="VERBOSE")


def test_default_values() -> None:
    s = Settings()
    assert s.app_env == "local"
    assert s.log_level == "INFO"
    assert s.aws_region == "us-east-1"
    assert s.default_rate_limit_rpm == 60
```

### Previous Story Learnings (from Story 1.1)

- **Use `uv venv .venv --python 3.11` + `uv pip install -r requirements-dev.txt`** for isolated environment — do not install globally
- **Ruff UP035 violation:** use `from collections.abc import Callable` not `from typing import Callable` (Python 3.9+); same for `Generator`, `AsyncGenerator`, `Awaitable` etc.
- **Import order matters for Ruff I001:** stdlib → third-party → first-party (`app.*`) — blank line between each group
- **Pre-commit hooks scope:** `app/` and `tests/` only — do not run on `.claude/` or `_bmad-output/`
- **`pydantic-settings>=2.2.0` is already in `requirements.txt`** — do not add it again
- **`app/core/__init__.py` and `app/utils/__init__.py` already exist** — do not recreate, just add new `.py` files alongside them
- **`tests/core/` may NOT exist** — Story 1.1 did not list it in the directory creation; verify before creating test files

### Anti-Patterns to Avoid

- **Do NOT** `import logging` in `app/core/config.py`, `app/core/middleware.py`, `app/api/v1/observability.py`, or any other module — `logging` is imported only in `app/utils/observability.py`
- **Do NOT** add a `MONGODB_URI` or any credential field to `Settings` — those are fetched at operation time via Secrets Manager (Story 1.5)
- **Do NOT** use `print()` anywhere — this story establishes `get_logger()` as the only output mechanism
- **Do NOT** use `datetime.utcnow()` — always `datetime.now(timezone.UTC)`
- **Do NOT** add routes to `app/main.py` — middleware registration and startup logging only
- **Do NOT** create `app/utils/secrets.py` content — that's Story 1.5
- **Do NOT** create `app/core/errors.py` content — that's Story 1.3
- **Do NOT** create `app/core/auth.py` or `app/core/rate_limiter.py` — those are Stories 1.6 and 1.7
- **Do NOT** implement `app/core/dependencies.py` — that's Story 1.4+
- **Do NOT** implement per-stage latency tracking in pipeline stages — `LatencyTracker` is created here as a utility; callers in pipeline stages are wired in later stories

### References

- [Source: architecture.md#D15] — Structured logging format specification (8-field JSON schema)
- [Source: architecture.md#Communication Patterns#Logging] — "always via the structured logger from `app/utils/observability.py` — never `print()`, never `import logging` directly"
- [Source: architecture.md#Enforcement Guidelines] — "All agents MUST" rules
- [Source: architecture.md#Foundation & Project Scaffold#Environment & Secrets] — `pydantic-settings` for typed settings; no secrets in `.env`
- [Source: architecture.md#Format Patterns#Datetime Handling] — `datetime.now(timezone.UTC)` exclusively
- [Source: architecture.md#Project Structure] — `app/core/config.py`, `app/core/middleware.py`, `app/utils/observability.py` file locations
- [Source: epics.md#Story 1.2] — User story, 3 acceptance criteria

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Fixed `timezone.UTC` → `from datetime import UTC` (Python 3.11 uses module-level `UTC` constant, not `timezone.UTC`)
- Used `RequestResponseEndpoint` from `starlette.middleware.base` for mypy strict compliance on `call_next` typing

### Completion Notes List

- Implemented `app/core/config.py`: `Settings(BaseSettings)` with typed fields, `@field_validator` for `log_level`, `@lru_cache` singleton `get_settings()`
- Implemented `app/utils/observability.py`: `JSONFormatter` producing 8-field JSON, `get_logger()`, `set_request_context()`, `LatencyTracker`
- Implemented `app/core/middleware.py`: `RequestIDMiddleware` injecting UUID v4 `request_id` into context and `X-Request-ID` response header
- Updated `app/main.py`: middleware registered before router, startup log with `operation="app_startup"`
- Updated `app/api/v1/observability.py`: `get_logger` wired into health endpoint
- Updated `.env.example`: added `DEFAULT_RATE_LIMIT_RPM=60`
- All 16 tests pass (5 config, 2 middleware, 6 observability, 3 pre-existing); ruff clean; mypy strict clean

### File List

- app/core/config.py (new)
- app/core/middleware.py (new)
- app/utils/observability.py (new)
- app/main.py (modified)
- app/api/v1/observability.py (modified)
- .env.example (modified)
- tests/core/__init__.py (new)
- tests/core/test_config.py (new)
- tests/core/test_middleware.py (new)
- tests/utils/test_observability.py (new)

## Change Log

- 2026-04-18: Implemented Story 1.2 — typed Settings class, structured JSON logger, RequestIDMiddleware, 16 tests, ruff + mypy strict clean (claude-sonnet-4-6)
