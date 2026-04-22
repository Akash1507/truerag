# Story 2.1: Tenant Registration & API Key Issuance

Status: done

## Story

As a Tenant Developer,
I want to register my team as a tenant and receive an API key,
so that my team has an isolated identity on the platform and can authenticate all subsequent API calls.

## Acceptance Criteria

**AC1:** Given a `POST /v1/tenants` request with a unique tenant name
When the request is processed
Then a new tenant document is created in the `tenants` MongoDB collection with `tenant_id`, `name`, `api_key_hash` (SHA-256 of the generated key), `rate_limit_rpm` (default from `settings.default_rate_limit_rpm`), `created_at`; the raw API key is returned once in the response body and never stored anywhere; HTTP 201 is returned

**AC2:** Given a `POST /v1/tenants` request with a tenant name that already exists
When the request is processed
Then HTTP 409 Conflict is returned with the standard error envelope; no duplicate tenant document is created

**AC3:** Given a successful tenant registration
When the returned API key is used in an `X-API-Key` header on a subsequent request
Then the existing auth middleware in `app/core/auth.py` resolves the tenant correctly via SHA-256 hash comparison against MongoDB — no changes to auth middleware hash logic required

## Tasks / Subtasks

- [x] Task 1: Extend `app/models/tenant.py` — add name + response schemas (AC1, AC3)
  - [x] 1.1 Add `name: str` field to `TenantDocument`
  - [x] 1.2 Ensure `tenant_id` maps correctly from MongoDB `_id` — use `Field(alias="_id")` with `model_config = ConfigDict(populate_by_name=True)` and a `field_validator` or `model_validator` to coerce `ObjectId` → `str`; alternatively store `tenant_id` as a separate string field alongside `_id` (simpler; avoids touching auth.py's `model_validate` call)
  - [x] 1.3 Add `TenantCreateRequest` Pydantic model (fields: `name: str`) for request body validation
  - [x] 1.4 Add `TenantCreateResponse` Pydantic model (fields: `tenant_id: str`, `name: str`, `api_key: str`, `rate_limit_rpm: int`, `created_at: datetime`) for the 201 response — `api_key` is the raw key returned once

- [x] Task 2: Add error codes + exceptions to `app/core/errors.py` (AC2)
  - [x] 2.1 Add `TENANT_ALREADY_EXISTS = "TENANT_ALREADY_EXISTS"` to `ErrorCode` enum
  - [x] 2.2 Add `TENANT_NOT_FOUND = "TENANT_NOT_FOUND"` to `ErrorCode` enum (used from Story 2.2; add now to avoid touching errors.py again next story)
  - [x] 2.3 Add `TenantAlreadyExistsError(TrueRAGError)` — `http_status=409`, `code=ErrorCode.TENANT_ALREADY_EXISTS`
  - [x] 2.4 Add `TenantNotFoundError(TrueRAGError)` — `http_status=404`, `code=ErrorCode.TENANT_NOT_FOUND`

- [x] Task 3: Create `app/services/tenant_service.py` (AC1, AC2, AC3)
  - [x] 3.1 Implement `async def create_tenant(name: str, db: AsyncIOMotorDatabase) -> tuple[TenantDocument, str]`: generate raw API key via `secrets.token_urlsafe(32)`, hash it via `hashlib.sha256(key.encode()).hexdigest()`, build the document dict, insert into `tenants` collection, return `(TenantDocument, raw_api_key)` — the raw key is ONLY returned here, never stored
  - [x] 3.2 Duplicate name check: before insert, call `find_one({"name": name})`; if doc exists, raise `TenantAlreadyExistsError`
  - [x] 3.3 Log with structured logger: `operation="create_tenant"`, include `tenant_id`, omit any key material
  - [x] 3.4 Use `datetime.now(UTC)` (import `from datetime import UTC`) — NEVER `datetime.utcnow()`

- [x] Task 4: Implement `POST /v1/tenants` in `app/api/v1/tenants.py` (AC1, AC2)
  - [x] 4.1 Add route `POST /v1/tenants` returning HTTP 201 with `TenantCreateResponse`
  - [x] 4.2 Inject `motor_client` via `request.app.state.motor_client` (same pattern as auth middleware)
  - [x] 4.3 Call `tenant_service.create_tenant(name, db)` — let `TenantAlreadyExistsError` propagate (the existing exception handler converts it to the error envelope)

- [x] Task 5: Auth bypass for `POST /v1/tenants` in `app/core/auth.py` (AC1, AC3)
  - [x] 5.1 Tenant registration must work without a prior API key (bootstrap problem: you cannot have a key before creating the first tenant)
  - [x] 5.2 Add method-aware bypass: alongside `SKIP_AUTH_PATHS` add `SKIP_AUTH_METHOD_PATHS: frozenset[tuple[str, str]] = frozenset({("POST", "/v1/tenants")})` and check `(request.method, path) in SKIP_AUTH_METHOD_PATHS` before the key check
  - [x] 5.3 `GET /v1/tenants` and `DELETE /v1/tenants/{tenant_id}` (Story 2.2) will remain auth-protected

- [x] Task 6: Write tests (AC1, AC2, AC3)
  - [x] 6.1 Create `tests/api/v1/test_tenants.py` — test POST /v1/tenants happy path (201, response has tenant_id + api_key), duplicate name (409), missing name field (422)
  - [x] 6.2 Create `tests/services/test_tenant_service.py` — unit-test `create_tenant`: success, duplicate raises `TenantAlreadyExistsError`, api_key_hash is SHA-256 of returned raw key, raw key not in stored document
  - [x] 6.3 Run `ruff check` and `mypy --strict` — must exit 0
  - [x] 6.4 Run `pytest tests/ -v` — all 116+ existing tests must pass; no regressions

## Dev Notes

### Auth Bypass for Tenant Registration

`app/core/auth.py` must be modified to let `POST /v1/tenants` through without a key. The current `SKIP_AUTH_PATHS` is path-only. Add a second set for method+path pairs:

```python
SKIP_AUTH_METHOD_PATHS: frozenset[tuple[str, str]] = frozenset({("POST", "/v1/tenants")})

# In AuthMiddleware.dispatch():
if path in SKIP_AUTH_PATHS or (request.method, path) in SKIP_AUTH_METHOD_PATHS:
    return await call_next(request)
```

This is the minimal change — the existing `SKIP_AUTH_PATHS` set is untouched. `GET /v1/tenants` and `DELETE /v1/tenants/{tenant_id}` remain auth-protected.

### TenantDocument: `tenant_id` Mapping from MongoDB

The existing `TenantDocument` has `tenant_id: str` but MongoDB auto-generates `_id: ObjectId`. The auth middleware calls `TenantDocument.model_validate(tenant_doc)` where `tenant_doc` is the raw Motor dict (contains `_id` as ObjectId, no `tenant_id` key). **This will fail with the current model if `tenant_id` is not stored as a separate field.**

**Recommended approach (minimal friction):** Store `tenant_id` as a separate `str` field in the document, set to `str(ObjectId())`:

```python
# in tenant_service.py
from bson import ObjectId

tenant_id = str(ObjectId())
doc = {
    "tenant_id": tenant_id,
    "name": name,
    "api_key_hash": hashed,
    "rate_limit_rpm": settings.default_rate_limit_rpm,
    "created_at": datetime.now(UTC),
}
await collection.insert_one(doc)
```

This means `find_one({"api_key_hash": key_hash})` in auth.py returns a dict that DOES have `tenant_id: str`, so `model_validate` works without changes. The `_id` field is auto-generated by MongoDB and ignored in `TenantDocument`.

Also add `name: str` to `TenantDocument` so the model fully represents the stored document.

**Do NOT use `Field(alias="_id")` approach** — it would require changes to auth.py's `model_validate` call and existing auth tests.

### API Key Generation — Reuse auth.py's `_hash_api_key`

`app/core/auth.py` already defines `_hash_api_key(raw_key: str) -> str` (SHA-256 hex digest). However, it is prefixed with `_` (private). In `tenant_service.py`, do NOT import `_hash_api_key` from auth (private convention). Re-implement the hash inline or move `_hash_api_key` to a shared location. Simplest: inline `hashlib.sha256(raw_key.encode()).hexdigest()` in the service — it is one line and avoids a circular-ish dependency on the auth module.

### tenant_service.py Pattern

No class needed — module-level async functions, consistent with `pii.py`, `secrets.py`, `retry.py`:

```python
# app/services/tenant_service.py
import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import get_settings
from app.core.errors import TenantAlreadyExistsError
from app.models.tenant import TenantDocument
from app.utils.observability import get_logger

logger = get_logger(__name__)


async def create_tenant(name: str, db: AsyncIOMotorDatabase[Any]) -> tuple[TenantDocument, str]:
    existing = await db["tenants"].find_one({"name": name})
    if existing:
        raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists")

    raw_key = secrets.token_urlsafe(32)
    api_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    tenant_id = str(ObjectId())
    settings = get_settings()
    now = datetime.now(UTC)

    doc: dict[str, Any] = {
        "tenant_id": tenant_id,
        "name": name,
        "api_key_hash": api_key_hash,
        "rate_limit_rpm": settings.default_rate_limit_rpm,
        "created_at": now,
    }
    await db["tenants"].insert_one(doc)

    tenant = TenantDocument(
        tenant_id=tenant_id,
        name=name,
        api_key_hash=api_key_hash,
        rate_limit_rpm=settings.default_rate_limit_rpm,
        created_at=now,
    )
    logger.info(
        "tenant_created",
        extra={"operation": "create_tenant", "extra_data": {"tenant_id": tenant_id}},
    )
    return tenant, raw_key
```

### Router Pattern for tenants.py

The router is registered at `/v1/tenants` in `app/api/v1/__init__.py` with prefix `/tenants` already. Routes must NOT be added to `main.py`. Inject the motor database via `request.app.state.motor_client`:

```python
from fastapi import APIRouter, Request, status
from app.models.tenant import TenantCreateRequest, TenantCreateResponse
from app.services import tenant_service
from app.core.config import get_settings

router = APIRouter()

@router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantCreateResponse)
async def register_tenant(body: TenantCreateRequest, request: Request) -> TenantCreateResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    tenant, raw_key = await tenant_service.create_tenant(body.name, db)
    return TenantCreateResponse(
        tenant_id=tenant.tenant_id,
        name=tenant.name,
        api_key=raw_key,
        rate_limit_rpm=tenant.rate_limit_rpm or settings.default_rate_limit_rpm,
        created_at=tenant.created_at,
    )
```

### Test Pattern — Mock MongoDB

Match the pattern from `tests/core/test_auth.py` — set `app.state.motor_client` directly:

```python
# tests/api/v1/test_tenants.py
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.main import create_app

def make_app_with_mock_db(find_one_return=None, insert_one_return=None):
    app = create_app()
    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=find_one_return)
    mock_collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id="abc"))
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = MagicMock()
    return app
```

Key test cases:
- `POST /v1/tenants` with `{"name": "acme"}` → 201, body has `tenant_id`, `api_key`, `name`, `rate_limit_rpm`, `created_at`; `api_key` is non-empty string
- `POST /v1/tenants` with duplicate name (find_one returns existing doc) → 409, `error.code == "TENANT_ALREADY_EXISTS"`
- `POST /v1/tenants` without name field → 422 (Pydantic validation)
- Verify `api_key` is NOT `api_key_hash`: `assert "hash" not in response_body["api_key"]` (belt-and-suspenders)

### Critical: Never Log or Return api_key_hash

- The `api_key_hash` is only in the DB document and in `TenantDocument`
- The `api_key` (raw) is only in the 201 response and never written to DB, log, or any other store
- `TenantCreateResponse` must NOT include `api_key_hash`
- Log messages must include `tenant_id` only — no key material

### Error Envelope Format

All non-2xx responses must follow:
```json
{"error": {"code": "TENANT_ALREADY_EXISTS", "message": "...", "request_id": "uuid"}}
```

The existing `exception_handlers.py` maps `TrueRAGError` → this envelope automatically. Do NOT raise `HTTPException` in business logic — raise typed errors only.

### MongoDB Collection Name

The collection is `"tenants"` (lowercase, per D1 architecture). Access via `db["tenants"]`.

### Existing Files to Modify

| File | Change |
|---|---|
| `app/models/tenant.py` | Add `name: str`; add `TenantCreateRequest`, `TenantCreateResponse` schemas |
| `app/core/errors.py` | Add `TENANT_ALREADY_EXISTS`, `TENANT_NOT_FOUND` to `ErrorCode`; add `TenantAlreadyExistsError`, `TenantNotFoundError` exception classes |
| `app/core/auth.py` | Add `SKIP_AUTH_METHOD_PATHS` frozenset; add method+path check in `dispatch()` |

### New Files to Create

| File | Purpose |
|---|---|
| `app/services/tenant_service.py` | `create_tenant()` function |
| `tests/api/v1/test_tenants.py` | API-level tests for POST /v1/tenants |
| `tests/services/test_tenant_service.py` | Unit tests for `create_tenant()` |

### Previously Established Patterns (from Stories 1.x)

- **`from datetime import UTC`** then `datetime.now(UTC)` — NEVER `datetime.utcnow()`
- **Built-in generics**: `list[X]`, `dict[K, V]`, `tuple[A, B]` — NOT `List`, `Dict`, `Tuple`
- **`X | None`** — NOT `Optional[X]`
- **`from typing import Any`** for `dict[str, Any]`
- **`StrEnum`** for error codes (already used in `errors.py`)
- **Never `print()` or `import logging`** — always `get_logger(__name__)` from `app/utils/observability.py`
- **ruff I001 import order**: stdlib → third-party → first-party — enforced by pre-commit
- **116 passing tests as baseline** — all must still pass after this story

### `pyproject.toml` / Requirements

`bson` (ObjectId) comes with `motor` / `pymongo` — no new dependency needed. `secrets` and `hashlib` are stdlib.

### Ruff / mypy

- Run `ruff check app/ tests/` — must exit 0
- Run `mypy app/ --strict` — must exit 0
- Common mypy issues to watch: `AsyncIOMotorDatabase` type parameter (`AsyncIOMotorDatabase[Any]`), `insert_one` return type

### Project Structure Notes

```
app/
├── models/tenant.py           ← MODIFY: add name, TenantCreateRequest, TenantCreateResponse
├── services/tenant_service.py ← NEW
├── api/v1/tenants.py          ← MODIFY: add POST /v1/tenants (currently empty router)
├── core/errors.py             ← MODIFY: add TENANT_ALREADY_EXISTS, TENANT_NOT_FOUND
└── core/auth.py               ← MODIFY: add SKIP_AUTH_METHOD_PATHS

tests/
├── api/v1/test_tenants.py     ← NEW
└── services/test_tenant_service.py ← NEW
```

`app/api/v1/__init__.py` already imports and registers `tenants.router` — no change needed there.

### Cross-Story Forward Notes (Do NOT implement now)

- Story 2.2 will add `GET /v1/tenants` and `DELETE /v1/tenants/{tenant_id}` — keep the router extensible
- `tenant_service.py` will grow with `list_tenants()`, `delete_tenant()` in Story 2.2 — do not pre-implement
- The `name` field uniqueness check uses `find_one({"name": name})` — Story 2.2 or later should add a MongoDB unique index on `name` for production safety, but that is out of scope here

### References

- [Source: epics.md#Story 2.1] — User story, 3 acceptance criteria
- [Source: architecture.md#D6] — API key format: `secrets.token_urlsafe(32)`, SHA-256 hash, `X-API-Key` header
- [Source: architecture.md#D1] — `tenants` collection schema: `tenant_id`, `api_key_hash`, `rate_limit_rpm`, `created_at`
- [Source: architecture.md#Naming Patterns] — snake_case fields, MongoDB fields, API fields
- [Source: architecture.md#Communication Patterns] — Typed exceptions, structured logging, error envelope
- [Source: architecture.md#FR Category to Structure Mapping] — Tenant Management: `app/api/v1/tenants.py`, `app/services/tenant_service.py`, `app/models/tenant.py`
- [Source: app/core/auth.py] — `_hash_api_key`, `SKIP_AUTH_PATHS`, `TenantDocument.model_validate` call site
- [Source: app/core/config.py] — `default_rate_limit_rpm = 60`
- [Source: story 1.9 dev notes] — 116 passing tests baseline, ruff/mypy patterns

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Pre-existing ruff E501 in `app/core/auth.py:75` fixed as part of this story (line-too-long in `_auth_error` call).
- All existing `TenantDocument` instantiations in tests lacked `name` field after adding it as required — updated `test_rate_limiter.py`, `test_auth.py`, `test_exception_handlers.py`.

### Completion Notes List

- Implemented `POST /v1/tenants` with HTTP 201, raw API key returned once and never stored.
- `tenant_id` stored as explicit `str` field (not `_id` alias) to maintain compatibility with `auth.py`'s `model_validate` call without changes.
- `SKIP_AUTH_METHOD_PATHS` added to auth middleware for bootstrap path; GET/DELETE remain auth-protected.
- 14 new tests added (7 API + 7 service); 130 total tests pass, ruff exits 0, mypy strict exits 0.

### File List

- `app/models/tenant.py` — modified: added `name: str` to `TenantDocument`; added `TenantCreateRequest`, `TenantCreateResponse`
- `app/core/errors.py` — modified: added `TENANT_ALREADY_EXISTS`, `TENANT_NOT_FOUND` to `ErrorCode`; added `TenantAlreadyExistsError`, `TenantNotFoundError`
- `app/services/tenant_service.py` — new: `create_tenant()` function
- `app/api/v1/tenants.py` — modified: implemented `POST /v1/tenants` route
- `app/core/auth.py` — modified: added `SKIP_AUTH_METHOD_PATHS`; fixed pre-existing ruff E501
- `tests/api/v1/test_tenants.py` — new: API-level tests for POST /v1/tenants
- `tests/services/test_tenant_service.py` — new: unit tests for `create_tenant()`
- `tests/core/test_rate_limiter.py` — modified: added `name` field to `TenantDocument` instantiations
- `tests/core/test_auth.py` — modified: added `name` field to tenant_doc fixture
- `tests/core/test_exception_handlers.py` — modified: added `name` field to `_FAKE_TENANT` dict

## Review Findings

_Code review conducted 2026-04-22 — 3 layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor)_

### Patches
- [x] [Review][Patch] Add strict validation to `TenantCreateRequest.name` — `min_length=1`, `max_length=100`, `strip_whitespace=True`, pattern `^[a-zA-Z0-9_-]+$` [app/models/tenant.py]
- [x] [Review][Patch] TOCTOU race condition — `find_one` + `insert_one` is non-atomic; catch `DuplicateKeyError` as `TenantAlreadyExistsError` [app/services/tenant_service.py]
- [x] [Review][Patch] `rate_limit_rpm or default` evaluates to default when `rate_limit_rpm == 0` — use `if tenant.rate_limit_rpm is not None` [app/api/v1/tenants.py]
- [x] [Review][Patch] Weak test assertion in `test_register_tenant_api_key_is_raw_not_hash` — fixed to assert `len(api_key) == 43` [tests/api/v1/test_tenants.py]
- [x] [Review][Patch] 409 test does not assert `request_id` is present in error envelope per spec [tests/api/v1/test_tenants.py]

### Deferred
- [x] [Review][Defer] Unauthenticated `POST /v1/tenants` has no secondary rate limit — known bootstrap design tradeoff, out of story 2.1 scope — deferred, pre-existing
- [x] [Review][Defer] `TenantDocument.rate_limit_rpm: int | None` — pre-existing model design, not introduced by this story — deferred, pre-existing
- [x] [Review][Defer] `insert_one` mutates `doc` dict in-place (adds `_id`) and no `extra="ignore"` on `TenantDocument` — latent, currently harmless — deferred, pre-existing
- [x] [Review][Defer] Two identity fields (`_id` MongoDB-auto + `tenant_id` app-generated) — documented architectural decision in Dev Notes — deferred, pre-existing
- [x] [Review][Defer] MongoDB connection failure during `create_tenant` returns generic 500 instead of `PROVIDER_UNAVAILABLE` — consistency improvement, out of story scope — deferred, pre-existing

## Change Log

- 2026-04-22: Story 2.1 implemented — tenant registration endpoint, API key issuance, auth bypass for bootstrap, error codes, 14 new tests (130 total passing)
- 2026-04-22: Code review complete — 1 decision-needed, 4 patches, 5 deferred, 6 dismissed
