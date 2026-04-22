# Story 2.2: Tenant Listing & Deletion

Status: review

## Story

As a Platform Admin,
I want to list all registered tenants and delete a tenant with all its associated data,
so that I can govern which teams are active on the platform (FR2, FR3).

## Acceptance Criteria

**AC1:** Given `GET /v1/tenants` with a valid API key
When the request is processed
Then it returns `{"items": [...], "next_cursor": "..."}` of tenant records (fields: `tenant_id`, `name`, `rate_limit_rpm`, `created_at` — `api_key_hash` is NEVER exposed); cursor-based pagination applies; an empty platform returns `{"items": [], "next_cursor": null}`

**AC2:** Given `DELETE /v1/tenants/{tenant_id}` for an existing tenant with no agents
When the request is processed
Then the tenant document is deleted from MongoDB and HTTP 204 No Content is returned

**AC3:** Given `DELETE /v1/tenants/{tenant_id}` for an existing tenant that has agents
When the request is processed
Then for each agent belonging to the tenant, `vector_store.delete_namespace("{tenant_id}_{agent_id}")` is called; all agent documents for the tenant are deleted from MongoDB; the tenant document is deleted; HTTP 204 is returned only after all deletions complete — no orphaned vector namespaces remain

**AC4:** Given `DELETE /v1/tenants/{tenant_id}` for a non-existent tenant
When the request is processed
Then HTTP 404 Not Found is returned with the standard error envelope (`TENANT_NOT_FOUND`)

**AC5:** Given `GET /v1/tenants` or `DELETE /v1/tenants/{tenant_id}` with no API key
When the request is processed
Then HTTP 401 is returned (existing AuthMiddleware handles this — no route changes needed)

## Tasks / Subtasks

- [x] Task 1: Create `app/utils/pagination.py` — cursor encode/decode utility (AC1)
  - [x] 1.1 Implement `encode_cursor(object_id: ObjectId) -> str` — base64url-encodes the str representation of a MongoDB ObjectId
  - [x] 1.2 Implement `decode_cursor(cursor: str) -> ObjectId` — decodes back to ObjectId for MongoDB range queries
  - [x] 1.3 Define `DEFAULT_PAGE_SIZE: int = 20`
  - [x] 1.4 Add `InvalidCursorError` handling: if `decode_cursor` receives a malformed string, raise `ValueError` (the route converts this to HTTP 400)

- [x] Task 2: Add response models to `app/models/tenant.py` (AC1)
  - [x] 2.1 Add `TenantListItem(BaseModel)` with fields: `tenant_id: str`, `name: str`, `rate_limit_rpm: int`, `created_at: datetime` — NO `api_key_hash` field
  - [x] 2.2 Add `TenantListResponse(BaseModel)` with fields: `items: list[TenantListItem]`, `next_cursor: str | None`
  - [x] 2.3 Address deferred: add `extra="ignore"` to `TenantDocument.model_config` so `_id` from MongoDB raw dicts doesn't cause Pydantic strict-extra errors if `model_validate` is ever called with a raw doc

- [x] Task 3: Add `list_tenants()` to `app/services/tenant_service.py` (AC1)
  - [x] 3.1 Signature: `async def list_tenants(db: AsyncIOMotorDatabase[Any], cursor: str | None, limit: int) -> tuple[list[TenantListItem], str | None]`
  - [x] 3.2 Build MongoDB query: if `cursor` provided, decode to ObjectId and filter `{"_id": {"$gt": decoded_oid}}`; if no cursor, query is `{}`
  - [x] 3.3 Fetch `limit + 1` documents sorted by `_id` ascending — the extra doc detects whether a next page exists without a second count query
  - [x] 3.4 If `len(raw_docs) > limit`: set `has_more=True`, trim to `raw_docs[:limit]`, encode cursor from `raw_docs[-1]["_id"]`; else `next_cursor=None`
  - [x] 3.5 Convert raw dicts to `TenantListItem` objects — use `doc["tenant_id"]`, `doc["name"]`, `doc.get("rate_limit_rpm", settings.default_rate_limit_rpm)`, `doc["created_at"]`
  - [x] 3.6 Log at DEBUG level: `operation="list_tenants"`, include result count

- [x] Task 4: Add `delete_tenant()` to `app/services/tenant_service.py` (AC2, AC3, AC4)
  - [x] 4.1 Signature: `async def delete_tenant(tenant_id: str, db: AsyncIOMotorDatabase[Any]) -> None`
  - [x] 4.2 Check tenant exists: `await db["tenants"].find_one({"tenant_id": tenant_id})` → if `None`, raise `TenantNotFoundError`
  - [x] 4.3 Find all agents: `await db["agents"].find({"tenant_id": tenant_id}).to_list(None)` — works even if `agents` collection doesn't exist yet (returns `[]`)
  - [x] 4.4 For each agent doc: resolve `vs_type = agent.get("vector_store", "pgvector")`, then `get_vector_store(vs_type)` from `app.core.dependencies`; call `await vector_store.delete_namespace(f"{tenant_id}_{agent['agent_id']}")` — if `ProviderUnavailableError` is raised (unknown backend), let it propagate as 503 (safer than leaving orphaned namespaces)
  - [x] 4.5 Delete agents: `await db["agents"].delete_many({"tenant_id": tenant_id})`
  - [x] 4.6 Delete tenant: `await db["tenants"].delete_one({"tenant_id": tenant_id})`
  - [x] 4.7 Log at INFO level: `operation="delete_tenant"`, include `tenant_id`, agent count deleted

- [x] Task 5: Add `GET /v1/tenants` to `app/api/v1/tenants.py` (AC1, AC5)
  - [x] 5.1 Route: `@router.get("", response_model=TenantListResponse)`
  - [x] 5.2 Parameters: `cursor: str | None = None`, `limit: int = DEFAULT_PAGE_SIZE`, `_: TenantDocument = Depends(get_current_tenant)` (auth guard — tenant identity not needed for listing)
  - [x] 5.3 Inject DB via `request.app.state.motor_client[settings.mongodb_database]`
  - [x] 5.4 Call `await tenant_service.list_tenants(db, cursor, limit)` and return `TenantListResponse`
  - [x] 5.5 Wrap `decode_cursor` in a try/except `ValueError` in the service and convert to HTTP 400 with `INVALID_CURSOR` code — OR raise `ValueError` and add a handler; keep it simple: validate cursor format before calling service

- [x] Task 6: Add `DELETE /v1/tenants/{tenant_id}` to `app/api/v1/tenants.py` (AC2, AC3, AC4, AC5)
  - [x] 6.1 Route: `@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)`
  - [x] 6.2 Parameters: `tenant_id: str` path param, `_: TenantDocument = Depends(get_current_tenant)` (auth guard)
  - [x] 6.3 Inject DB via `request.app.state.motor_client[settings.mongodb_database]`
  - [x] 6.4 Call `await tenant_service.delete_tenant(tenant_id, db)` — `TenantNotFoundError` propagates to 404 via existing exception handler; `ProviderUnavailableError` propagates to 503
  - [x] 6.5 Return `None` (FastAPI 204 No Content sends no body)

- [x] Task 7: Write tests (AC1–AC5)
  - [x] 7.1 Create `tests/utils/test_pagination.py` — unit-test `encode_cursor`/`decode_cursor` round-trip; test malformed cursor raises `ValueError`
  - [x] 7.2 Extend `tests/api/v1/test_tenants.py` — add GET tests: empty list, single tenant, cursor pagination (response includes `next_cursor`); add DELETE tests: 204 happy path (no agents), 404 for unknown tenant_id, 401 for missing API key
  - [x] 7.3 Extend `tests/services/test_tenant_service.py` — unit-test `list_tenants`: empty DB, multiple tenants, cursor decoding; unit-test `delete_tenant`: success with no agents, raises `TenantNotFoundError`, calls `delete_namespace` for each agent then deletes agents then tenant (order verified via mock call order)
  - [x] 7.4 Run `ruff check app/ tests/` — must exit 0
  - [x] 7.5 Run `mypy app/ --strict` — must exit 0
  - [x] 7.6 Run `pytest tests/ -v` — all 133+ existing tests must pass; no regressions

## Dev Notes

### New File: `app/utils/pagination.py`

This file does NOT exist yet — create it. Architecture (D11) specifies cursor = base64-encoded MongoDB ObjectId of last document in the page:

```python
import base64
from bson import ObjectId

DEFAULT_PAGE_SIZE: int = 20


def encode_cursor(object_id: ObjectId) -> str:
    return base64.urlsafe_b64encode(str(object_id).encode()).decode()


def decode_cursor(cursor: str) -> ObjectId:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        return ObjectId(raw)
    except Exception as exc:
        raise ValueError(f"Invalid cursor: {cursor!r}") from exc
```

`bson` is available via `motor`/`pymongo` — no new dependency.

### `list_tenants()` — Pagination Pattern

Use `limit + 1` fetch trick — single query, no secondary count:

```python
async def list_tenants(
    db: AsyncIOMotorDatabase[Any],
    cursor: str | None,
    limit: int,
) -> tuple[list[TenantListItem], str | None]:
    query: dict[str, Any] = {}
    if cursor:
        oid = decode_cursor(cursor)  # raises ValueError on bad cursor
        query["_id"] = {"$gt": oid}

    raw_docs: list[dict[str, Any]] = (
        await db["tenants"].find(query).sort("_id", 1).limit(limit + 1).to_list(None)
    )

    has_more = len(raw_docs) > limit
    if has_more:
        raw_docs = raw_docs[:limit]

    next_cursor: str | None = encode_cursor(raw_docs[-1]["_id"]) if has_more else None
    settings = get_settings()
    items = [
        TenantListItem(
            tenant_id=doc["tenant_id"],
            name=doc["name"],
            rate_limit_rpm=doc.get("rate_limit_rpm") or settings.default_rate_limit_rpm,
            created_at=doc["created_at"],
        )
        for doc in raw_docs
    ]
    return items, next_cursor
```

**Critical:** Sort by `_id` (MongoDB ObjectId) for consistent ordering — not by `created_at`. ObjectIds embed a timestamp and are always monotonically increasing, making them ideal for stable cursor pagination.

### `delete_tenant()` — Deletion Sequence & Vector Store

The deletion must follow this exact order to satisfy "no orphaned vector namespaces remain":
1. Verify tenant exists → 404 if not
2. Find all agents for the tenant
3. For each agent: call `delete_namespace` on its vector store backend
4. Delete all agent MongoDB documents
5. Delete tenant MongoDB document

```python
from app.core.dependencies import get_vector_store

async def delete_tenant(tenant_id: str, db: AsyncIOMotorDatabase[Any]) -> None:
    tenant_doc = await db["tenants"].find_one({"tenant_id": tenant_id})
    if not tenant_doc:
        raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

    agents: list[dict[str, Any]] = (
        await db["agents"].find({"tenant_id": tenant_id}).to_list(None)
    )

    for agent in agents:
        vs_type: str = agent.get("vector_store", "pgvector")
        agent_id: str = agent["agent_id"]
        namespace = f"{tenant_id}_{agent_id}"
        vector_store = get_vector_store(vs_type)  # ProviderUnavailableError → 503
        await vector_store.delete_namespace(namespace)

    await db["agents"].delete_many({"tenant_id": tenant_id})
    await db["tenants"].delete_one({"tenant_id": tenant_id})

    logger.info(
        "tenant_deleted",
        extra={
            "operation": "delete_tenant",
            "extra_data": {"tenant_id": tenant_id, "agents_deleted": len(agents)},
        },
    )
```

**IMPORTANT — `VECTOR_STORE_REGISTRY` is currently empty** (populated in Epic 4). If an agent with `vector_store: "pgvector"` exists in MongoDB right now, `get_vector_store("pgvector")` raises `ProviderUnavailableError` → HTTP 503. This is correct behaviour — safer than silently leaving orphaned namespace data. In practice, no agents exist yet (Story 2.3 creates them), so this path is not exercised in Story 2.2 tests.

**Namespace format (D8):** `{tenant_id}_{agent_id}` — both are 24-char hex strings from ObjectId. Never hardcode this format: always construct as `f"{tenant_id}_{agent_id}"`.

### Router Pattern

Both new routes follow the same DB-injection pattern as `POST /v1/tenants`:

```python
from fastapi import APIRouter, Depends, Query, Request, status

from app.core.auth import get_current_tenant
from app.models.tenant import (
    TenantCreateRequest,
    TenantCreateResponse,
    TenantListResponse,
)
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()

@router.get("", response_model=TenantListResponse)
async def list_tenants_route(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    _: TenantDocument = Depends(get_current_tenant),
) -> TenantListResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    items, next_cursor = await tenant_service.list_tenants(db, cursor, limit)
    return TenantListResponse(items=items, next_cursor=next_cursor)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_route(
    tenant_id: str,
    request: Request,
    _: TenantDocument = Depends(get_current_tenant),
) -> None:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    await tenant_service.delete_tenant(tenant_id, db)
```

**`limit` validation:** Use `Query(ge=1, le=100)` to prevent abuse. FastAPI returns 422 automatically on constraint violation.

### Test Pattern for Auth-Required Endpoints

`GET /v1/tenants` and `DELETE /v1/tenants/{tenant_id}` require a valid `X-API-Key`. The `AuthMiddleware` calls `find_one({"api_key_hash": hash})` on the `tenants` collection. Design the mock so `find_one` returns a valid tenant document regardless of the query (mock doesn't validate the filter):

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.main import create_app

FAKE_CALLER = {
    "tenant_id": "caller-id",
    "name": "caller",
    "api_key_hash": "any-hash",
    "rate_limit_rpm": 60,
    "created_at": datetime.now(UTC),
}

FAKE_API_KEY = "test-key-value"  # any string; auth mock ignores actual hash


def make_authed_app_for_list(tenant_docs: list[dict]) -> FastAPI:
    """App where any API key resolves to FAKE_CALLER; find() returns tenant_docs."""
    app = create_app()
    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=FAKE_CALLER)

    # Cursor chain: find().sort().limit().to_list()
    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=tenant_docs)
    mock_collection.find = MagicMock(return_value=mock_cursor)

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)

    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = MagicMock()
    return app
```

Key: `find_one` returns `FAKE_CALLER` (satisfies auth), `find()` cursor chain returns `tenant_docs` (satisfies list business logic). Both use the same mock_collection.

For **DELETE tests**, `find_one` must return different docs depending on the query:
- Auth check: `find_one({"api_key_hash": hash})` → return FAKE_CALLER
- Tenant existence check: `find_one({"tenant_id": tenant_id})` → return tenant doc or None

Use `side_effect` to differentiate:
```python
def find_one_side_effect(query: dict) -> dict | None:
    if "api_key_hash" in query:
        return FAKE_CALLER
    if "tenant_id" in query:
        return TENANT_DOC  # or None for 404 test
    return None

mock_collection.find_one = AsyncMock(side_effect=find_one_side_effect)
```

`delete_one` and `delete_many`: mock as `AsyncMock(return_value=MagicMock(deleted_count=1))`.

### `delete_tenant()` — Agent Test with Mock Vector Store

For the test where agents exist, mock `get_vector_store` to return a mock VectorStore:
```python
from unittest.mock import AsyncMock, patch

mock_vs = MagicMock()
mock_vs.delete_namespace = AsyncMock(return_value=None)

with patch("app.services.tenant_service.get_vector_store", return_value=mock_vs):
    await tenant_service.delete_tenant("t1", db)

mock_vs.delete_namespace.assert_called_once_with("t1_agent-id-1")
```

### Error Codes — No New Codes Needed

`TENANT_NOT_FOUND` and `TenantNotFoundError` already exist in `app/core/errors.py` from Story 2.1. Do NOT add new codes — no new error scenarios beyond 404 are introduced in this story.

### `TenantDocument.model_config` — Add `extra="ignore"`

From deferred work: `insert_one` mutates the inserted dict in-place by adding `_id`. If `model_validate` is ever called on a raw MongoDB document containing `_id`, Pydantic silently ignores it (default behavior), but this is not documented. Make it explicit:

```python
class TenantDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
```

This is a safe, non-breaking change.

### MongoDB `agents` Collection Access

The `agents` collection is queried in `delete_tenant` but is defined in Story 2.3. At this stage:
- The collection may not exist in MongoDB yet — Motor returns `[]` from `find()` on a non-existent collection. No error handling needed.
- The agent document schema (`agent_id`, `vector_store`, `tenant_id` fields) must match what Story 2.3 will implement. Specifically, `agent_id` must be a string field stored explicitly (not `_id` alias) — consistent with how `tenant_id` is stored in the `tenants` collection.

### Previously Established Patterns (Must Follow)

- **`from datetime import UTC`** then `datetime.now(UTC)` — NEVER `datetime.utcnow()`
- **Built-in generics**: `list[X]`, `dict[K, V]`, `tuple[A, B]` — NOT `List`, `Dict`, `Tuple`
- **`X | None`** — NOT `Optional[X]`
- **Never `print()` or `import logging`** — always `get_logger(__name__)` from `app/utils/observability.py`
- **ruff I001 import order**: stdlib → third-party → first-party
- **Never raise `HTTPException` in services** — raise typed `TrueRAGError` subclasses only; exception handlers convert them
- **Never hardcode error codes as strings** — use `ErrorCode` enum from `app/core/errors.py`
- **Namespace format**: always `f"{tenant_id}_{agent_id}"` — never hardcode or reconstruct differently
- **133 passing tests as baseline** — all must still pass after this story

### `Query()` for `limit` Parameter

Use `fastapi.Query` to constrain `limit`:
```python
limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100)
```
This auto-returns 422 if `limit < 1` or `limit > 100` — no manual validation needed.

### Project Structure Notes

```
app/
├── utils/pagination.py          ← NEW: encode_cursor, decode_cursor, DEFAULT_PAGE_SIZE
├── models/tenant.py             ← MODIFY: add TenantListItem, TenantListResponse; add extra="ignore" to TenantDocument.model_config
├── services/tenant_service.py   ← MODIFY: add list_tenants(), delete_tenant()
└── api/v1/tenants.py            ← MODIFY: add GET "" and DELETE "/{tenant_id}" routes

tests/
├── utils/test_pagination.py     ← NEW: unit tests for encode/decode cursor
├── api/v1/test_tenants.py       ← MODIFY: add GET and DELETE endpoint tests
└── services/test_tenant_service.py ← MODIFY: add list_tenants(), delete_tenant() unit tests
```

`app/api/v1/__init__.py` already registers `tenants.router` — no change needed.

### References

- [Source: epics.md#Story 2.2] — User story, acceptance criteria (FR2, FR3)
- [Source: architecture.md#D1] — `tenants` collection schema; `agents` collection schema (tenant_id, agent_id, vector_store fields)
- [Source: architecture.md#D8] — Namespace format: `{tenant_id}_{agent_id}`
- [Source: architecture.md#D11] — Pagination cursor format: base64 ObjectId, `?cursor=`, list response envelope
- [Source: architecture.md#D10] — Error envelope: `{error: {code, message, request_id}}`
- [Source: architecture.md#Naming Patterns] — snake_case, MongoDB fields, API fields
- [Source: architecture.md#Communication Patterns] — Typed exceptions, structured logging
- [Source: architecture.md#Structure Patterns] — Test location mirrors app/ structure
- [Source: app/core/dependencies.py] — `get_vector_store(key: str) -> VectorStore`
- [Source: app/providers/registry.py] — `VECTOR_STORE_REGISTRY` (currently empty; populated Epic 4)
- [Source: app/core/auth.py] — `get_current_tenant(request)` FastAPI dependency
- [Source: app/core/errors.py] — `TenantNotFoundError`, `ProviderUnavailableError` already defined
- [Source: story 2.1 dev notes] — 133 tests baseline, mock DB pattern, `find_one_side_effect` approach, tenant_id as explicit str field
- [Source: deferred-work.md] — `extra="ignore"` on TenantDocument deferred from 2.1 review

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

None — implementation proceeded without blockers.

### Completion Notes List

- Implemented `app/utils/pagination.py`: `encode_cursor`, `decode_cursor` (base64url of MongoDB ObjectId), `DEFAULT_PAGE_SIZE=20`. Invalid cursors raise `ValueError`.
- Added `TenantListItem` and `TenantListResponse` models to `app/models/tenant.py`; added `extra="ignore"` to `TenantDocument.model_config` (deferred from 2.1).
- Added `list_tenants()` to `app/services/tenant_service.py`: limit+1 fetch trick for cursor pagination, sorted by `_id` ascending.
- Added `delete_tenant()` to `app/services/tenant_service.py`: verifies tenant exists → 404, calls `delete_namespace` per agent, deletes agents, then tenant (strict order).
- Added `GET /v1/tenants` route: auth-guarded via `Depends(get_current_tenant)`, `ValueError` from bad cursor converted to HTTP 400.
- Added `DELETE /v1/tenants/{tenant_id}` route: auth-guarded, `TenantNotFoundError` propagates to 404, `ProviderUnavailableError` to 503.
- All 153 tests pass (133 baseline + 20 new); ruff and mypy --strict both clean.

### File List

- `app/utils/pagination.py` (new)
- `app/models/tenant.py` (modified)
- `app/services/tenant_service.py` (modified)
- `app/api/v1/tenants.py` (modified)
- `tests/utils/test_pagination.py` (new)
- `tests/api/v1/test_tenants.py` (modified)
- `tests/services/test_tenant_service.py` (modified)

## Change Log

- 2026-04-22: Story 2.2 implemented — tenant listing (cursor pagination) and deletion (with agent namespace cleanup). 20 new tests added, 153 total passing.
