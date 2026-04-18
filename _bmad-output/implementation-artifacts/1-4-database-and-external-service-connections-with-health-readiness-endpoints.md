# Story 1.4: Database & External Service Connections with Health/Readiness Endpoints

Status: done

## Story

As an AI Platform Engineer,
I want all database and AWS service clients established as FastAPI lifespan dependencies, with working health and readiness endpoints,
So that infrastructure monitoring can verify platform liveness and the availability of all five dependencies (FR49).

## Acceptance Criteria

**AC1:** Given the FastAPI app lifespan
When the application starts
Then a `motor` MongoDB client, `asyncpg` pgvector connection pool, and `aioboto3` sessions for SQS, S3, DynamoDB, and Secrets Manager are all initialised; failure to connect to any critical dependency raises a startup error naming the failing dependency

**AC2:** Given `GET /v1/health`
When called at any time
Then it returns HTTP 200 with `{"status": "ok"}` — this endpoint does not check dependencies; it confirms the process is alive

**AC3:** Given `GET /v1/ready` when all dependencies are reachable
When the endpoint responds
Then it returns HTTP 200 with a JSON body showing the status of all five dependencies: MongoDB, pgvector, SQS, DynamoDB, and S3

**AC4:** Given `GET /v1/ready` when any dependency is unreachable
When the endpoint responds
Then it returns HTTP 503 with the error envelope identifying the failing dependency and the `request_id`

## Tasks / Subtasks

- [x] Task 1: Add connection settings to `app/core/config.py` (AC: 1)
  - [x] 1.1 Add `mongodb_uri: str = "mongodb://localhost:27017"` — used in lifespan; production value overridden via env var or will be replaced by secrets wrapper in Story 1.5
  - [x] 1.2 Add `pgvector_dsn: str = "postgresql://postgres:postgres@localhost:5432/truerag"` — local dev default
  - [x] 1.3 Add `aws_endpoint_url: str | None = None` — allows override to LocalStack URL for local dev (e.g., `http://localhost:4566`)
  - [x] 1.4 Add `sqs_ingestion_queue_url: str = "http://localhost:4566/000000000000/truerag-ingestion"` — queue URL used for readiness check
  - [x] 1.5 Add `s3_document_bucket: str = "truerag-documents"` — bucket name used for readiness check
  - [x] 1.6 Add `dynamodb_audit_table: str = "truerag-audit-log"` and `dynamodb_jobs_table: str = "truerag-ingestion-jobs"` — table names for readiness check

- [x] Task 2: Initialise all clients in `app/main.py` lifespan (AC: 1)
  - [x] 2.1 Import `motor.motor_asyncio.AsyncIOMotorClient`, `asyncpg`, `aioboto3` at top of `app/main.py`
  - [x] 2.2 In `lifespan()`, initialise MongoDB: `motor_client = AsyncIOMotorClient(settings.mongodb_uri)`; verify by calling `await motor_client.admin.command("ping")`; on failure raise `RuntimeError(f"MongoDB connection failed: {e}")`
  - [x] 2.3 Initialise asyncpg pool: `pg_pool = await asyncpg.create_pool(settings.pgvector_dsn, min_size=2, max_size=10)`; verify by calling `await pg_pool.fetchval("SELECT 1")`; on failure raise `RuntimeError(f"pgvector connection failed: {e}")`
  - [x] 2.4 Initialise aioboto3 session: `aws_session = aioboto3.Session()`; store in `app.state.aws_session`; note — aioboto3 sessions are lightweight and do not perform network I/O at creation; service-level readiness is verified via `GET /v1/ready`, not at startup
  - [x] 2.5 Store all clients in `app.state`: `application.state.motor_client = motor_client`, `application.state.pg_pool = pg_pool`, `application.state.aws_session = aws_session`
  - [x] 2.6 On startup failure, log the error via `get_logger(__name__).error(...)` before re-raising so CloudWatch captures it
  - [x] 2.7 On lifespan shutdown (after `yield`): call `motor_client.close()` and `await pg_pool.close()`; swallow any shutdown errors with a warning log — do NOT let shutdown errors mask the real shutdown
  - [x] 2.8 Pass `settings = get_settings()` at the top of `lifespan()` — do not call `get_settings()` at module level in `lifespan()`

- [x] Task 3: Fix observability router prefix and add `/v1/ready` endpoint (AC: 2, 3, 4)
  - [x] 3.1 **CRITICAL FIX:** In `app/api/v1/__init__.py`, change `router.include_router(observability.router, prefix="/observability", ...)` to `router.include_router(observability.router, tags=["observability"])` — removes the `/observability` path segment so endpoints are at `/v1/health` and `/v1/ready` as the architecture specifies (currently broken: lives at `/v1/observability/health`)
  - [x] 3.2 In `app/api/v1/observability.py`, add `GET /ready` handler `async def readiness_check(request: Request) -> JSONResponse`; import `Request` from `fastapi`
  - [x] 3.3 `readiness_check` probes all five dependencies by calling `request.app.state.*` clients; on any failure raise `ProviderUnavailableError(f"<dependency_name> unavailable: {e}")` — the exception handler maps this to HTTP 503 with the error envelope including `request_id`
  - [x] 3.4 On all-ok, return `JSONResponse(content={"mongodb": "ok", "pgvector": "ok", "sqs": "ok", "dynamodb": "ok", "s3": "ok"})`
  - [x] 3.5 Import `ProviderUnavailableError` from `app.core.errors` in `observability.py`
  - [x] 3.6 Log start and result of readiness check at INFO level: `logger.info("readiness_check", extra={"operation": "readiness_check", "extra_data": {"result": "ok"}})`

- [x] Task 4: Implement individual dependency probes (AC: 3, 4)
  - [x] 4.1 MongoDB probe: `await request.app.state.motor_client.admin.command("ping")` — returns `{"ok": 1}` on success; wrap in try/except
  - [x] 4.2 pgvector probe: `await request.app.state.pg_pool.fetchval("SELECT 1")` — returns `1` on success; wrap in try/except
  - [x] 4.3 SQS probe: use `async with request.app.state.aws_session.client("sqs", ...) as sqs: await sqs.get_queue_attributes(QueueUrl=settings.sqs_ingestion_queue_url, AttributeNames=["ApproximateNumberOfMessages"])`; wrap in try/except
  - [x] 4.4 DynamoDB probe: use `async with ... as dynamodb: await dynamodb.describe_table(TableName=settings.dynamodb_audit_table)`; wrap in try/except
  - [x] 4.5 S3 probe: use `async with ... as s3: await s3.head_bucket(Bucket=settings.s3_document_bucket)`; wrap in try/except
  - [x] 4.6 When creating AWS service clients inside readiness_check, pass `endpoint_url=settings.aws_endpoint_url` (if set) and `region_name=settings.aws_region` — this allows LocalStack override for local dev

- [x] Task 5: Write tests (AC: 1, 2, 3, 4)
  - [x] 5.1 Create `tests/api/v1/test_observability.py`
  - [x] 5.2 Test `GET /v1/health` → 200, body `{"status": "ok"}` — no mocking needed, standalone endpoint
  - [x] 5.3 Test `GET /v1/ready` with all dependencies healthy: mock `app.state.motor_client.admin.command`, `app.state.pg_pool.fetchval`, `app.state.aws_session.client` context managers returning success → assert 200, body contains `{"mongodb": "ok", "pgvector": "ok", "sqs": "ok", "dynamodb": "ok", "s3": "ok"}`
  - [x] 5.4 Test `GET /v1/ready` with MongoDB down: mock `motor_client.admin.command` to raise `Exception("connection refused")` → assert 503, error envelope body `{"error": {"code": "PROVIDER_UNAVAILABLE", "message": "...", "request_id": "..."}}`
  - [x] 5.5 Test `GET /v1/ready` with pgvector down: similar to 5.4 but mock `pg_pool.fetchval` to raise
  - [x] 5.6 Test `GET /v1/ready` with SQS down: mock `sqs.get_queue_attributes` to raise → assert 503
  - [x] 5.7 Test `GET /v1/health` is at `/v1/health` (not `/v1/observability/health`) — assert status 200 using TestClient
  - [x] 5.8 Create test fixtures for mocking `app.state` clients; use `TestClient` from `fastapi.testclient` (sync client, same as Story 1.3)
- [x] 5.9 Run `ruff check app/ tests/` — must exit 0
- [x] 5.10 Run `mypy app/ --strict` — must exit 0
- [x] 5.11 Run `pytest tests/ -v` — all tests must pass

### Review Findings

- [x] [Review][Patch] Update middleware tests to call the moved health route [tests/core/test_middleware.py:7]
- [x] [Review][Patch] Exercise lifespan startup in observability tests so AC1 is actually verified [tests/api/v1/test_observability.py:38]
- [x] [Review][Patch] Close the asyncpg pool when post-creation validation fails [app/main.py:39]

## Dev Notes

### Critical Architecture Rules (must not violate)

- **`app.state` is the ONLY place connection objects live** — never module-level globals; `app.state.motor_client`, `app.state.pg_pool`, `app.state.aws_session`
- **Never raise `HTTPException` from `readiness_check`** — raise `ProviderUnavailableError` and let the exception handler (Story 1.3) convert to 503 with error envelope
- **All logging via `get_logger(__name__)`** — never `import logging` directly; never `print()`
- **`/v1/health` and `/v1/ready` are at the root of the v1 prefix** — NOT under `/v1/observability/` — the current router registration is wrong and MUST be fixed in Task 3.1
- **`aioboto3` session creation is not a network call** — only service client context managers (`async with session.client(...)`) make network calls; session can be initialised synchronously at startup
- **Probe timeout**: AWS service probes during readiness check may hang if VPC routing is misconfigured; no explicit timeout is required for Story 1.4 (keep it simple), but the probe calls are inherently bounded by the OS TCP timeout

### File Locations

```
app/core/config.py                    ← MODIFY: add 6 new settings fields
app/main.py                           ← MODIFY: add client initialisation in lifespan
app/api/v1/__init__.py                ← MODIFY: fix observability router prefix (remove "/observability")
app/api/v1/observability.py           ← MODIFY: add GET /ready handler
tests/api/v1/test_observability.py    ← NEW: tests for /health and /ready
```

### Current State of Existing Files

**`app/main.py`** — lifespan currently just logs startup and yields. Add client init before `yield`, cleanup after.

**`app/api/v1/observability.py`** — currently has only `GET /health` returning `{"status": "ok"}`. Keep this unchanged; add `GET /ready` alongside it.

**`app/api/v1/__init__.py`** — current registration:
```python
router.include_router(observability.router, prefix="/observability", tags=["observability"])
```
Must change to (remove prefix):
```python
router.include_router(observability.router, tags=["observability"])
```
**This is a breaking fix** — /health was previously at /v1/observability/health (wrong); after fix it is at /v1/health (correct per architecture spec). Any existing test for /v1/observability/health must be updated.

**`app/core/config.py`** — has `mongodb_secret_name` and `pgvector_secret_name` already. Keep those (used by Story 1.5 secrets wrapper). Add the direct URI settings alongside them for Story 1.4.

### Lifespan Pattern (authoritative implementation)

```python
# app/main.py

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aioboto3
import asyncpg
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.core.errors import TrueRAGError
from app.core.exception_handlers import generic_exception_handler, truerag_exception_handler
from app.core.middleware import RequestIDMiddleware
from app.utils.observability import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info("startup", extra={"operation": "app_startup"})

    # MongoDB
    try:
        motor_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)  # type: ignore[type-arg]
        await motor_client.admin.command("ping")
        application.state.motor_client = motor_client
        logger.info("mongodb_connected", extra={"operation": "app_startup"})
    except Exception as exc:
        logger.error("mongodb_failed", extra={"operation": "app_startup", "extra_data": {"error": str(exc)}})
        raise RuntimeError(f"MongoDB connection failed: {exc}") from exc

    # pgvector
    try:
        pg_pool = await asyncpg.create_pool(settings.pgvector_dsn, min_size=2, max_size=10)
        await pg_pool.fetchval("SELECT 1")
        application.state.pg_pool = pg_pool
        logger.info("pgvector_connected", extra={"operation": "app_startup"})
    except Exception as exc:
        motor_client.close()
        logger.error("pgvector_failed", extra={"operation": "app_startup", "extra_data": {"error": str(exc)}})
        raise RuntimeError(f"pgvector connection failed: {exc}") from exc

    # AWS (lightweight — no network I/O at session creation)
    application.state.aws_session = aioboto3.Session()
    logger.info("aws_session_created", extra={"operation": "app_startup"})

    yield

    # Shutdown
    try:
        motor_client.close()
    except Exception as exc:
        logger.warning("mongodb_close_error", extra={"operation": "app_shutdown", "extra_data": {"error": str(exc)}})
    try:
        await pg_pool.close()
    except Exception as exc:
        logger.warning("pgvector_close_error", extra={"operation": "app_shutdown", "extra_data": {"error": str(exc)}})
    logger.info("shutdown", extra={"operation": "app_shutdown"})
```

### Readiness Handler Pattern (authoritative)

```python
# app/api/v1/observability.py

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.utils.observability import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health")
async def health_check() -> JSONResponse:
    logger.info("health_check", extra={"operation": "health_check"})
    return JSONResponse(content={"status": "ok"})


@router.get("/ready")
async def readiness_check(request: Request) -> JSONResponse:
    settings = get_settings()
    logger.info("readiness_check_start", extra={"operation": "readiness_check"})

    # MongoDB
    try:
        await request.app.state.motor_client.admin.command("ping")
    except Exception as exc:
        raise ProviderUnavailableError(f"mongodb unavailable: {exc}") from exc

    # pgvector
    try:
        await request.app.state.pg_pool.fetchval("SELECT 1")
    except Exception as exc:
        raise ProviderUnavailableError(f"pgvector unavailable: {exc}") from exc

    # SQS
    try:
        async with request.app.state.aws_session.client(
            "sqs", region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url
        ) as sqs:
            await sqs.get_queue_attributes(
                QueueUrl=settings.sqs_ingestion_queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
    except Exception as exc:
        raise ProviderUnavailableError(f"sqs unavailable: {exc}") from exc

    # DynamoDB
    try:
        async with request.app.state.aws_session.client(
            "dynamodb", region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url
        ) as dynamodb:
            await dynamodb.describe_table(TableName=settings.dynamodb_audit_table)
    except Exception as exc:
        raise ProviderUnavailableError(f"dynamodb unavailable: {exc}") from exc

    # S3
    try:
        async with request.app.state.aws_session.client(
            "s3", region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url
        ) as s3:
            await s3.head_bucket(Bucket=settings.s3_document_bucket)
    except Exception as exc:
        raise ProviderUnavailableError(f"s3 unavailable: {exc}") from exc

    logger.info("readiness_check_ok", extra={"operation": "readiness_check", "extra_data": {"result": "ok"}})
    return JSONResponse(content={"mongodb": "ok", "pgvector": "ok", "sqs": "ok", "dynamodb": "ok", "s3": "ok"})
```

### Config Settings to Add

```python
# app/core/config.py additions

mongodb_uri: str = "mongodb://localhost:27017"
pgvector_dsn: str = "postgresql://postgres:postgres@localhost:5432/truerag"
aws_endpoint_url: str | None = None  # Set to "http://localhost:4566" for LocalStack
sqs_ingestion_queue_url: str = "http://localhost:4566/000000000000/truerag-ingestion"
s3_document_bucket: str = "truerag-documents"
dynamodb_audit_table: str = "truerag-audit-log"
dynamodb_jobs_table: str = "truerag-ingestion-jobs"
```

### Test Pattern

```python
# tests/api/v1/test_observability.py

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import create_app


def make_test_app_with_mocked_state() -> FastAPI:
    """Create app instance with mocked app.state for dependency-free readiness tests."""
    application = create_app()

    mock_motor = MagicMock()
    mock_motor.admin.command = AsyncMock(return_value={"ok": 1})

    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=1)

    mock_session = MagicMock()
    # Mock the async context managers for SQS, DynamoDB, S3
    mock_sqs = AsyncMock()
    mock_sqs.get_queue_attributes = AsyncMock(return_value={})
    mock_dynamodb = AsyncMock()
    mock_dynamodb.describe_table = AsyncMock(return_value={})
    mock_s3 = AsyncMock()
    mock_s3.head_bucket = AsyncMock(return_value={})
    mock_session.client.return_value.__aenter__ = AsyncMock(side_effect=[mock_sqs, mock_dynamodb, mock_s3])
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    application.state.motor_client = mock_motor
    application.state.pg_pool = mock_pool
    application.state.aws_session = mock_session
    return application
```

Note: The test client does NOT go through the lifespan by default — use `with TestClient(app)` if you need lifespan to run, or set state manually on the app instance.

### Dependencies Already in requirements.txt

All required packages are already present — no new dependencies needed:
- `motor>=3.4.0` — MongoDB async driver
- `asyncpg>=0.29.0` — PostgreSQL async driver
- `aioboto3>=13.0.0` — AWS async SDK wrapper

### Previous Story Learnings (from Story 1.3)

- **`app/core/__init__.py` and `app/core/errors.py`** already exist — do NOT recreate; `ProviderUnavailableError` is already defined there
- **`tests/api/v1/` directory** may or may not have `__init__.py`; add it if absent
- **Ruff UP035:** use `from collections.abc import AsyncGenerator` not `from typing import AsyncGenerator`
- **Import order for ruff I001:** stdlib → third-party → first-party (`app.*`) with blank lines between groups
- **`StrEnum` (Python 3.11)** is the ruff-preferred pattern — use `class Foo(StrEnum)` if adding enums
- **mypy strict requires explicit return annotations** — all handlers must have `-> JSONResponse` or `-> None`
- **`# type: ignore[arg-type]`** needed for `add_exception_handler(TrueRAGError, ...)` — already in `main.py`
- **`AsyncIOMotorClient` is generic** in motor 3.x — mypy strict may require `# type: ignore[type-arg]`; the motor stubs are incomplete and this is a known upstream limitation

### Anti-Patterns to Avoid

- **Do NOT** store clients as module-level globals — always `app.state.*`
- **Do NOT** raise `HTTPException` from `readiness_check` — use `ProviderUnavailableError`
- **Do NOT** create a new `aioboto3.Session()` per request — reuse `app.state.aws_session`; sessions are not thread-unsafe but creating many is wasteful
- **Do NOT** import `aioboto3` in `observability.py` — the session is accessed via `request.app.state.aws_session` (already created in lifespan)
- **Do NOT** leave the `/health` endpoint at `/v1/observability/health` — this breaks ALB and k8s health probe routing
- **Do NOT** add retry logic to lifespan connection attempts — fail fast at startup; let ECS restart the task; retry decorator (Story 1.5) is for runtime provider calls, not startup
- **Do NOT** create `app/core/auth.py` or `app/core/rate_limiter.py` — those are Stories 1.6 and 1.7
- **Do NOT** create `app/utils/secrets.py` — that is Story 1.5
- **Do NOT** call Secrets Manager in this story to retrieve the MongoDB URI — use the direct URI settings from `config.py`; Story 1.5 adds the secrets wrapper

### References

- [Source: architecture.md#D3] — Async driver stack: motor, asyncpg, aioboto3
- [Source: architecture.md#Project Structure] — `app/api/v1/observability.py`: `/v1/metrics`, `/v1/health`, `/v1/ready`
- [Source: architecture.md#Data Boundary] — MongoDB via motor, pgvector via asyncpg, S3/SQS/DynamoDB via aioboto3
- [Source: architecture.md#D12] — ECS topology: API task and worker task share no in-process state
- [Source: epics.md#Story 1.4] — User story and 4 acceptance criteria
- [Source: architecture.md#Communication Patterns] — ProviderUnavailableError → 503 mapping

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Completion Notes List

- Added 7 new settings fields to `Settings` in `app/core/config.py`: `mongodb_uri`, `pgvector_dsn`, `aws_endpoint_url`, `sqs_ingestion_queue_url`, `s3_document_bucket`, `dynamodb_audit_table`, `dynamodb_jobs_table`
- Implemented full lifespan in `app/main.py`: motor MongoDB ping, asyncpg pool + SELECT 1 verify, aioboto3 session (no-network), all stored in `app.state`; shutdown cleanly closes motor and pg_pool with warning-level swallowed errors
- Fixed critical router prefix bug in `app/api/v1/__init__.py`: removed `prefix="/observability"` so health/ready are now at `/v1/health` and `/v1/ready` (not `/v1/observability/health`)
- Implemented `GET /ready` handler in `app/api/v1/observability.py` with all five dependency probes (MongoDB ping, pgvector SELECT 1, SQS get_queue_attributes, DynamoDB describe_table, S3 head_bucket); raises `ProviderUnavailableError` → 503 on any failure
- Added `# type: ignore[import-untyped]` for `aioboto3` and `asyncpg` (missing stubs, known upstream limitation)
- Key test pattern: `TestClient(app)` without context manager skips lifespan — enables setting `app.state.*` mock clients directly; all 6 new tests + 44 existing tests pass; ruff and mypy --strict pass

### File List

- `app/core/config.py` — modified: added 7 new connection/AWS settings fields
- `app/main.py` — modified: added motor/asyncpg/aioboto3 lifespan init and shutdown
- `app/api/v1/__init__.py` — modified: removed `/observability` prefix from observability router
- `app/api/v1/observability.py` — modified: added `GET /ready` handler with 5 dependency probes
- `tests/api/v1/test_observability.py` — new: 6 tests covering /health and /ready scenarios

## Change Log

- 2026-04-18: Story 1.4 created — database connections lifespan, motor/asyncpg/aioboto3 init, /v1/health and /v1/ready endpoints, fix observability router prefix (claude-sonnet-4-6)
- 2026-04-18: Story 1.4 implemented — all 5 tasks complete, 6 tests added, ruff+mypy pass, 50/50 tests green (claude-sonnet-4-6)
