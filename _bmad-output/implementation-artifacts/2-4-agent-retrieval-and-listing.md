# Story 2.4: Agent Retrieval & Listing

Status: review

## Story

As a Tenant Developer,
I want to retrieve an individual agent's configuration and list all agents under my tenant,
so that I can inspect the current pipeline config and see what agents my team has registered (FR7, FR8).

## Acceptance Criteria

**AC1:** Given `GET /v1/agents/{agent_id}` for an agent belonging to the calling tenant
When the request is processed
Then the full agent config document is returned with all pipeline fields and `status`; HTTP 200 is returned

**AC2:** Given `GET /v1/agents/{agent_id}` for an agent belonging to a different tenant
When the request is processed
Then HTTP 403 Forbidden is returned with the error envelope; the agent data is not exposed

**AC3:** Given `GET /v1/agents/{agent_id}` for a non-existent agent ID
When the request is processed
Then HTTP 404 Not Found is returned with `AGENT_NOT_FOUND` code

**AC4:** Given `GET /v1/agents` for a tenant with multiple agents
When the request is processed
Then a paginated list `{"items": [...], "next_cursor": "..."|null}` of agent documents is returned for that tenant only; agents from other tenants are never included

## Tasks / Subtasks

- [x] Task 1: Add `AgentNotFoundError` to `app/core/errors.py` (AC3)
  - [x] 1.1 `AGENT_NOT_FOUND` is already present in `ErrorCode(StrEnum)` — do NOT add it again
  - [x] 1.2 Add `AgentNotFoundError(TrueRAGError)` — `code=ErrorCode.AGENT_NOT_FOUND`, `http_status=404`, default message `"Agent not found"`

- [x] Task 2: Add `AgentListResponse` model to `app/models/agent.py` (AC4)
  - [x] 2.1 Add after `AgentCreateResponse`:
    ```python
    class AgentListResponse(BaseModel):
        items: list[AgentCreateResponse]
        next_cursor: str | None
    ```
  - [x] 2.2 No other model changes — `AgentDocument` and `AgentCreateResponse` are unchanged

- [x] Task 3: Add `get_agent()` and `list_agents()` to `app/services/agent_service.py` (AC1–AC4)
  - [x] 3.1 Add imports at top of file (after existing imports):
    ```python
    from app.core.errors import AgentAlreadyExistsError, AgentConfigInvalidError, AgentNotFoundError, ForbiddenError
    from app.utils.pagination import DEFAULT_PAGE_SIZE, decode_cursor, encode_cursor
    ```
  - [x] 3.2 Add `get_agent()` function:
    ```python
    async def get_agent(
        agent_id: str,
        tenant_id: str,
        db: AsyncIOMotorDatabase[Any],
    ) -> AgentDocument:
        doc = await db["agents"].find_one({"agent_id": agent_id})
        if doc is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")
        if doc["tenant_id"] != tenant_id:
            raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")
        return AgentDocument(**{k: doc[k] for k in AgentDocument.model_fields})
    ```
    Note: `extra="ignore"` on `AgentDocument` suppresses MongoDB `_id` during model construction.

  - [x] 3.3 Add `list_agents()` function:
    ```python
    async def list_agents(
        tenant_id: str,
        db: AsyncIOMotorDatabase[Any],
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[AgentDocument], str | None]:
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if cursor:
            oid = decode_cursor(cursor)  # raises ValueError on invalid cursor — caught at route layer
            query["_id"] = {"$gt": oid}

        raw_docs: list[dict[str, Any]] = (
            await db["agents"].find(query).sort("_id", 1).limit(limit + 1).to_list(None)
        )

        has_more = len(raw_docs) > limit
        if has_more:
            raw_docs = raw_docs[:limit]

        next_cursor: str | None = encode_cursor(raw_docs[-1]["_id"]) if has_more else None
        items = [
            AgentDocument(**{k: doc[k] for k in AgentDocument.model_fields})
            for doc in raw_docs
        ]

        logger.debug(
            "list_agents",
            extra={"operation": "list_agents", "extra_data": {"count": len(items), "tenant_id": tenant_id}},
        )
        return items, next_cursor
    ```
    Tenant isolation is structural: `query` always filters by `tenant_id` — agents from other tenants are never fetched.

- [x] Task 4: Add `GET /v1/agents/{agent_id}` and `GET /v1/agents` routes to `app/api/v1/agents.py` (AC1–AC4)
  - [x] 4.1 Add imports to the top of the file (after existing imports):
    ```python
    from fastapi import APIRouter, Depends, Query, Request, status
    from app.core.errors import ForbiddenError, InvalidCursorError
    from app.models.agent import AgentCreateRequest, AgentCreateResponse, AgentListResponse
    from app.utils.pagination import DEFAULT_PAGE_SIZE
    ```
  - [x] 4.2 Add `GET /v1/agents/{agent_id}` route after `create_agent_route`:
    ```python
    @router.get("/{agent_id}", response_model=AgentCreateResponse)
    async def get_agent_route(
        agent_id: str,
        request: Request,
        caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
    ) -> AgentCreateResponse:
        settings = get_settings()
        db = request.app.state.motor_client[settings.mongodb_database]
        agent = await agent_service.get_agent(agent_id, caller.tenant_id, db)
        return AgentCreateResponse(**agent.model_dump())
    ```
  - [x] 4.3 Add `GET /v1/agents` route after `get_agent_route`:
    ```python
    @router.get("", response_model=AgentListResponse)
    async def list_agents_route(
        request: Request,
        cursor: str | None = Query(default=None),
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
        caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
    ) -> AgentListResponse:
        settings = get_settings()
        db = request.app.state.motor_client[settings.mongodb_database]
        try:
            items, next_cursor = await agent_service.list_agents(caller.tenant_id, db, cursor, limit)
        except ValueError as exc:
            raise InvalidCursorError(str(exc)) from exc
        return AgentListResponse(
            items=[AgentCreateResponse(**item.model_dump()) for item in items],
            next_cursor=next_cursor,
        )
    ```
  - [x] 4.4 Route registration order MATTERS for FastAPI: `GET ""` must be registered AFTER `POST ""` but BEFORE `GET "/{agent_id}"` to avoid path conflicts. Final router order:
    1. `POST ""` — create_agent_route (existing)
    2. `GET ""` — list_agents_route (NEW)
    3. `GET "/{agent_id}"` — get_agent_route (NEW)

- [x] Task 5: Write tests (AC1–AC4)
  - [x] 5.1 Update `tests/api/v1/test_agents.py` — extend `make_authed_app` and add new tests:

    **Extend `make_authed_app` to support `find` cursor mock:**
    ```python
    def make_authed_app(
        find_one_return: dict | None = None,
        find_return_list: list[dict] | None = None,
    ) -> FastAPI:
        app = create_app()
        mock_collection = MagicMock()

        def find_one_side_effect(query: dict) -> dict | None:
            if "api_key_hash" in query:
                return FAKE_CALLER
            return find_one_return

        mock_collection.find_one = AsyncMock(side_effect=find_one_side_effect)
        mock_collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake-oid"))

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=find_return_list or [])
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
    This is additive — add `find_return_list` param and the cursor mock. All existing POST tests pass `find_one_return` only; they remain unaffected.

    **Tests for `GET /v1/agents/{agent_id}`:**
    - `test_get_agent_200_happy_path` — `find_one_return` = full agent doc with `tenant_id == FAKE_CALLER["tenant_id"]` → 200, all fields present, `status == "active"`
    - `test_get_agent_403_different_tenant` — `find_one_return` = agent doc with `tenant_id == "other-tenant"` → 403, `FORBIDDEN`
    - `test_get_agent_404_not_found` — `find_one_return = None` → 404, `AGENT_NOT_FOUND`
    - `test_get_agent_401_no_api_key` — no `X-API-Key` header → 401

    **Tests for `GET /v1/agents`:**
    - `test_list_agents_200_empty` — `find_return_list=[]` → 200, `items==[]`, `next_cursor==null`
    - `test_list_agents_200_with_agents` — `find_return_list=[full_agent_doc]` → 200, `items` has 1 entry, all fields correct
    - `test_list_agents_400_invalid_cursor` — `?cursor=notbase64` → 400, `INVALID_CURSOR`
    - `test_list_agents_401_no_api_key` — no `X-API-Key` → 401

  - [x] 5.2 Update `tests/services/test_agent_service.py` — add tests for `get_agent` and `list_agents`:

    **Tests for `get_agent`:**
    - `test_get_agent_success` — mock `find_one` returns valid doc with matching `tenant_id` → returns `AgentDocument` with correct fields
    - `test_get_agent_not_found` — mock `find_one` returns `None` → raises `AgentNotFoundError`
    - `test_get_agent_wrong_tenant` — mock `find_one` returns doc with `tenant_id == "other-tenant"`, caller `tenant_id == "caller-id"` → raises `ForbiddenError`

    **Tests for `list_agents`:**
    - `test_list_agents_empty` — mock `to_list` returns `[]` → items=[], next_cursor=None
    - `test_list_agents_with_items` — mock `to_list` returns 2 agent docs → items has 2 `AgentDocument`s, next_cursor=None
    - `test_list_agents_pagination_has_more` — `limit=1`, `to_list` returns 2 docs → items has 1, next_cursor is set (non-None string)
    - `test_list_agents_invalid_cursor` — call with `cursor="notvalidbase64!!"` → raises `ValueError`

  - [x] 5.3 Run `ruff check app/ tests/` — must exit 0
  - [x] 5.4 Run `mypy app/ --strict` — must exit 0
  - [x] 5.5 Run `pytest tests/ -v` — all 189 tests pass (174 existing + 15 new); no regressions

## Dev Notes

### Critical: `AGENT_NOT_FOUND` Already in ErrorCode

`ErrorCode.AGENT_NOT_FOUND = "AGENT_NOT_FOUND"` is already defined in `app/core/errors.py:11`. Only the *exception class* `AgentNotFoundError` is missing — do NOT add the enum value again or it will break.

Similarly, `INVALID_CURSOR` and `InvalidCursorError` are both already defined — import directly for use in route.

### Cross-Tenant Access Pattern for `get_agent`

The `get_agent` service performs two sequential lookups:
1. `find_one({"agent_id": agent_id})` — fetches doc regardless of tenant
2. Check `doc["tenant_id"] != tenant_id` → raise `ForbiddenError`

This order (fetch first, auth second) is intentional and matches the PRD requirement: 404 for non-existent, 403 for wrong tenant. Do NOT reverse the order (403 before 404 would leak existence information to attackers).

### Pagination Pattern — Match `list_tenants` Exactly

`list_agents` mirrors `list_tenants` from `app/services/tenant_service.py` identically, except:
- Query always includes `"tenant_id": tenant_id` filter (structural isolation — tenants list is admin-only, agents list is tenant-scoped)
- Returns `list[AgentDocument]` instead of `list[TenantListItem]`

Key pattern (copy verbatim):
```python
raw_docs = await db["agents"].find(query).sort("_id", 1).limit(limit + 1).to_list(None)
has_more = len(raw_docs) > limit
if has_more:
    raw_docs = raw_docs[:limit]
next_cursor = encode_cursor(raw_docs[-1]["_id"]) if has_more else None
```

`decode_cursor` raises `ValueError` on invalid input — this is intentional. The service does NOT catch it. The route catches `ValueError` and converts to `InvalidCursorError`, consistent with the `list_tenants_route` pattern in `app/api/v1/tenants.py:46`.

### Route Registration Order in `agents.py`

FastAPI registers routes in the order they appear. `GET ""` must be registered before `GET "/{agent_id}"` to prevent FastAPI from treating an empty path segment as `agent_id`. Final router order in `agents.py`:
1. `POST ""` (existing)
2. `GET ""` (list) — NEW
3. `GET "/{agent_id}"` (single) — NEW

### `make_authed_app` Extension — Backward Compatible

Adding `find_return_list: list[dict] | None = None` as a keyword arg with default `None` is fully backward compatible with all existing POST tests — they pass no new arg and get `find_return_list=None` (which resolves to `[]` via `or []`).

The mock cursor chain:
```python
mock_cursor.sort = MagicMock(return_value=mock_cursor)   # .sort("_id", 1) → self
mock_cursor.limit = MagicMock(return_value=mock_cursor)  # .limit(n) → self
mock_cursor.to_list = AsyncMock(return_value=...)        # await .to_list(None)
mock_collection.find = MagicMock(return_value=mock_cursor)
```
This chains correctly because the service calls `.find(query).sort(...).limit(...).to_list(None)`.

### Constructing `AgentDocument` from MongoDB Doc

Both `get_agent` and `list_agents` construct `AgentDocument` from raw MongoDB docs using:
```python
AgentDocument(**{k: doc[k] for k in AgentDocument.model_fields})
```
This extracts only the declared model fields, skipping `_id`. The `extra="ignore"` on `AgentDocument` provides a secondary safeguard. Consistent with `create_agent()` in the same file.

### Response Shape for Both GET Endpoints

`GET /v1/agents/{agent_id}` response model = `AgentCreateResponse` (same shape as POST 201 response). Route converts: `AgentCreateResponse(**agent.model_dump())`.

`GET /v1/agents` response model = `AgentListResponse` (new model). Route converts each item: `[AgentCreateResponse(**item.model_dump()) for item in items]`.

Both follow the same pattern: service returns `AgentDocument`(s), route converts to response model.

### `GET /v1/agents/{agent_id}` Test — `find_one_return` Disambiguation

In the test, `find_one` is called twice:
1. Auth check: `{"api_key_hash": ...}` → returns `FAKE_CALLER`
2. Agent lookup: `{"agent_id": agent_id}` → returns `find_one_return`

The existing `find_one_side_effect` already handles this correctly via the `"api_key_hash" in query` discriminator.

For `test_get_agent_403_different_tenant`, construct the return doc with `tenant_id` set to a value that does NOT match `FAKE_CALLER["tenant_id"]`:
```python
doc = {**FAKE_AGENT_DOC, "tenant_id": "other-tenant-id"}
app = make_authed_app(find_one_return=doc)
```

### Test Fixtures — Full Agent Doc for Tests

Define `FAKE_AGENT_DOC` at module level in both test files:
```python
FAKE_AGENT_DOC = {
    "agent_id": "507f1f77bcf86cd799439011",
    "tenant_id": FAKE_CALLER["tenant_id"],  # matches caller
    "name": "my-rag-agent",
    "chunking_strategy": "fixed_size",
    "vector_store": "pgvector",
    "embedding_provider": "openai",
    "llm_provider": "anthropic",
    "retrieval_mode": "dense",
    "reranker": "none",
    "top_k": 10,
    "semantic_cache_enabled": False,
    "semantic_cache_threshold": None,
    "status": "active",
    "created_at": datetime.now(UTC),
    "updated_at": datetime.now(UTC),
    "_id": ObjectId("507f1f77bcf86cd799439011"),  # MongoDB _id — suppressed by extra="ignore"
}
```

### Previously Established Patterns (Must Follow)

- `from datetime import UTC` then `datetime.now(UTC)` — NEVER `datetime.utcnow()`
- Built-in generics: `list[X]`, `dict[K, V]`, `tuple[A, B]` — NOT `List`, `Dict`, `Tuple`
- `X | None` — NOT `Optional[X]`
- Never `print()` or `import logging` — always `get_logger(__name__)` from `app/utils/observability.py`
- ruff I001 import order: stdlib → third-party → first-party
- Never raise `HTTPException` in services — raise typed `TrueRAGError` subclasses only
- Never hardcode error codes as strings — use `ErrorCode` enum
- `extra="ignore"` on `AgentDocument` — suppresses MongoDB `_id` during deserialization
- 174 passing tests as baseline — all must still pass after this story

### Files Changed

**Modified files only — no new files:**
```
app/
├── core/errors.py            ← ADD: AgentNotFoundError class
├── models/agent.py           ← ADD: AgentListResponse model
├── services/agent_service.py ← ADD: get_agent(), list_agents()
└── api/v1/agents.py          ← ADD: GET /{agent_id} and GET "" routes

tests/
├── api/v1/test_agents.py        ← EXTEND: make_authed_app + new tests
└── services/test_agent_service.py ← ADD: get_agent and list_agents tests
```

### Project Structure Notes

- All routes for agents stay in `app/api/v1/agents.py` — the router is already registered in `app/api/v1/__init__.py`
- No changes to `app/main.py` — agents indexes already created in lifespan (Story 2.3)
- No changes to `app/core/auth.py`, `app/core/rate_limiter.py`, or middleware

### References

- [Source: epics.md#Story 2.4] — User story and all acceptance criteria (FR7, FR8)
- [Source: architecture.md#D1] — `agents` collection schema; `agent_id` as explicit str field, not `_id` alias
- [Source: architecture.md#D10] — Error envelope: `{error: {code, message, request_id}}`
- [Source: architecture.md#D11] — Pagination cursor format: base64-encoded ObjectId, `?cursor=`, `_id > decoded_cursor`
- [Source: app/utils/pagination.py] — `encode_cursor`, `decode_cursor`, `DEFAULT_PAGE_SIZE=20`
- [Source: app/core/errors.py] — `AGENT_NOT_FOUND` already in ErrorCode; `AgentNotFoundError` missing; `InvalidCursorError` exists
- [Source: app/services/tenant_service.py#list_tenants] — pagination pattern to mirror exactly
- [Source: app/api/v1/tenants.py#list_tenants_route] — ValueError → InvalidCursorError conversion pattern
- [Source: app/services/agent_service.py] — existing `create_agent` signature and doc construction patterns
- [Source: app/models/agent.py] — `AgentDocument`, `AgentCreateResponse` — response shape for both GET endpoints
- [Source: tests/api/v1/test_agents.py] — existing `make_authed_app` and `find_one_side_effect` pattern; extend don't replace
- [Source: story 2.3 dev notes] — 174 tests baseline; `extra="ignore"` on document models; cross-tenant detection at route layer

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- Added `AgentNotFoundError` to `app/core/errors.py` (Task 1) — `AGENT_NOT_FOUND` enum value was already present; only the exception class was missing.
- Added `AgentListResponse` model to `app/models/agent.py` (Task 2) — wraps `list[AgentCreateResponse]` + `next_cursor`.
- Added `get_agent()` and `list_agents()` to `app/services/agent_service.py` (Task 3) — fetch-then-auth order for `get_agent` prevents existence leakage; `list_agents` mirrors `list_tenants` cursor pattern exactly with structural tenant isolation via `query` filter.
- Added `GET ""` (list) and `GET "/{agent_id}"` (single) routes to `app/api/v1/agents.py` (Task 4) — registered in correct FastAPI order: POST → GET "" → GET "/{agent_id}".
- 15 new tests added across API and service layers; all 189 tests pass. ruff and mypy --strict both clean.

### File List

app/core/errors.py
app/models/agent.py
app/services/agent_service.py
app/api/v1/agents.py
tests/api/v1/test_agents.py
tests/services/test_agent_service.py

### Change Log

- 2026-04-26: Implemented Story 2.4 — agent retrieval (`GET /v1/agents/{agent_id}`) and listing (`GET /v1/agents`) with cursor pagination, cross-tenant 403 guard, and 15 new tests.
