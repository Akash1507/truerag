# Story 2.6: Agent Deletion

Status: review

## Story

As a Tenant Developer,
I want to delete a RAG Agent and its isolated namespace synchronously,
so that the agent and all its associated resources are fully removed in a single operation with no orphaned data (FR9).

## Acceptance Criteria

**AC1:** Given `DELETE /v1/agents/{agent_id}` for an agent belonging to the calling tenant
When the request is processed
Then the agent document is deleted from MongoDB AND `vector_store.delete_namespace("{tenant_id}_{agent_id}")` is called synchronously — HTTP 204 is returned only after both operations complete

**AC2:** Given `DELETE /v1/agents/{agent_id}` for an agent that has ingested documents
When the request is processed
Then all document records for that agent are also deleted from MongoDB alongside the agent document and the vector store namespace — no orphaned document records remain

**AC3:** Given `DELETE /v1/agents/{agent_id}` for an agent belonging to a different tenant
When the request is processed
Then HTTP 403 Forbidden is returned; no deletion occurs

**AC4:** Given `DELETE /v1/agents/{agent_id}` for a non-existent agent
When the request is processed
Then HTTP 404 Not Found is returned

## Tasks / Subtasks

- [x] Task 1: Add `delete_agent()` to `app/services/agent_service.py` (AC1–AC4)
  - [x] 1.1 Add `get_vector_store` to imports at top of file:
    ```python
    from app.core.dependencies import get_vector_store
    ```
  - [x] 1.2 Add `delete_agent()` after `update_agent_config()`:
    ```python
    async def delete_agent(
        agent_id: str,
        tenant_id: str,
        db: AsyncIOMotorDatabase[Any],
    ) -> None:
        doc = await db["agents"].find_one({"agent_id": agent_id})
        if doc is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")
        if doc["tenant_id"] != tenant_id:
            raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")

        vs_type: str = doc.get("vector_store", "pgvector")
        namespace = f"{tenant_id}_{agent_id}"

        await db["documents"].delete_many({"agent_id": agent_id})
        await db["agents"].delete_one({"agent_id": agent_id})

        vector_store = get_vector_store(vs_type)
        await vector_store.delete_namespace(namespace)

        logger.info(
            "agent_deleted",
            extra={
                "operation": "delete_agent",
                "extra_data": {"agent_id": agent_id, "tenant_id": tenant_id},
            },
        )
    ```

- [x] Task 2: Add `DELETE /{agent_id}` route to `app/api/v1/agents.py` (AC1–AC4)
  - [x] 2.1 Add `status` is already imported — verify `status.HTTP_204_NO_CONTENT` is available (it is)
  - [x] 2.2 Add DELETE route after `update_agent_config_route`:
    ```python
    @router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_agent_route(
        agent_id: str,
        request: Request,
        caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
    ) -> None:
        settings = get_settings()
        db = request.app.state.motor_client[settings.mongodb_database]
        await agent_service.delete_agent(agent_id, caller.tenant_id, db)
    ```
  - [x] 2.3 Final router registration order in `agents.py` (document for clarity):
    1. `POST ""` — create_agent_route
    2. `GET ""` — list_agents_route
    3. `GET "/{agent_id}"` — get_agent_route
    4. `PATCH "/{agent_id}/config"` — update_agent_config_route
    5. `DELETE "/{agent_id}"` — delete_agent_route (NEW)

- [x] Task 3: Write tests (AC1–AC4)
  - [x] 3.1 Extend `tests/services/test_agent_service.py`:

    **Add `patch` to imports:**
    ```python
    from unittest.mock import AsyncMock, MagicMock, patch
    ```

    **Add `delete_agent` to the agent_service import:**
    ```python
    from app.services.agent_service import create_agent, delete_agent, get_agent, list_agents, update_agent_config
    ```

    **Extend `make_mock_db` — add `delete_one` and `delete_many` to both `mock_agents` and `mock_documents`:**
    ```python
    mock_agents.delete_one = AsyncMock(return_value=MagicMock())
    mock_agents.delete_many = AsyncMock(return_value=MagicMock())
    mock_documents.delete_one = AsyncMock(return_value=MagicMock())
    mock_documents.delete_many = AsyncMock(return_value=MagicMock())
    ```
    This is backward-compatible — new kwargs with defaults, existing callers unaffected.

    **New tests for `delete_agent`:**

    - `test_delete_agent_success_no_documents` — `find_one` returns `FAKE_AGENT_DOC`, `documents_find_one_return=None`; mock `get_vector_store`; assert `delete_many({"agent_id": ...})` called on documents, `delete_one({"agent_id": ...})` called on agents, `delete_namespace(f"{tenant_id}_{agent_id}")` called once
    - `test_delete_agent_success_calls_correct_namespace` — verify namespace format is exactly `f"{FAKE_AGENT_DOC['tenant_id']}_{FAKE_AGENT_DOC['agent_id']}"`
    - `test_delete_agent_success_with_documents` — same as above but `documents_find_one_return={"doc_id": "x"}` (documents exist); verify `delete_many` is still called (existence doesn't change behavior — always cascade delete)
    - `test_delete_agent_not_found` — `find_one` returns `None` → raises `AgentNotFoundError`; `delete_one`, `delete_many`, `delete_namespace` NOT called
    - `test_delete_agent_wrong_tenant` — `find_one` returns doc with `tenant_id="other-tenant"` → raises `ForbiddenError`; no deletes called
    - `test_delete_agent_vector_store_key_from_doc` — agent doc has `vector_store="qdrant"`; verify `get_vector_store("qdrant")` is called (not hardcoded "pgvector")

    **Pattern for patching `get_vector_store` in agent_service tests:**
    ```python
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        await delete_agent(agent_id, tenant_id, db)
    ```

  - [x] 3.2 Extend `tests/api/v1/test_agents.py`:

    **Extend `make_authed_app` — add `delete_one` and `delete_many` to `mock_agents` and `mock_documents`:**
    ```python
    mock_agents.delete_one = AsyncMock(return_value=MagicMock())
    mock_agents.delete_many = AsyncMock(return_value=MagicMock())
    mock_documents.delete_one = AsyncMock(return_value=MagicMock())
    mock_documents.delete_many = AsyncMock(return_value=MagicMock())
    ```

    **New tests for `DELETE /v1/agents/{agent_id}`:**

    - `test_delete_agent_204_success` — `find_one` returns `FAKE_AGENT_DOC`; patch `get_vector_store`; `DELETE /v1/agents/{agent_id}` → 204, response body is empty
    - `test_delete_agent_404_not_found` — `find_one_return=None` → 404, `AGENT_NOT_FOUND`
    - `test_delete_agent_403_wrong_tenant` — `find_one_return={...FAKE_AGENT_DOC, "tenant_id": "other"}` → 403, `FORBIDDEN`
    - `test_delete_agent_401_no_api_key` — no `X-API-Key` header → 401

    **Pattern for 204 assertion:**
    ```python
    assert response.status_code == 204
    assert response.content == b""  # no response body on 204
    ```

    **Pattern for patching `get_vector_store` in API tests:**
    ```python
    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        response = await client.delete(f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}", ...)
    ```

  - [x] 3.3 Run `ruff check app/ tests/` — must exit 0
  - [x] 3.4 Run `mypy app/ --strict` — must exit 0
  - [x] 3.5 Run `pytest tests/ -v` — all tests pass (205 existing + ~10 new); no regressions

## Dev Notes

### Service Implementation: Follow `delete_tenant` Pattern Exactly

`app/services/tenant_service.py:98-121` already implements the identical pattern for bulk agent deletion during tenant teardown. The `delete_agent` function is a single-agent variant of the same pattern.

Key parts to replicate:
- `get_vector_store` from `app.core.dependencies` (already imported in `tenant_service.py`)
- Namespace: `f"{tenant_id}_{agent_id}"` — hardcoded format per D8
- `vs_type = doc.get("vector_store", "pgvector")` — read from agent doc, default "pgvector"

### Deletion Order: Documents → Agent → Vector Namespace

Order matters for consistency:
1. `delete_many({"agent_id": agent_id})` on `documents` collection — cascade delete all doc records
2. `delete_one({"agent_id": agent_id})` on `agents` collection — remove agent
3. `vector_store.delete_namespace(namespace)` — remove vector data

Documents collection may not exist yet (Epic 3 creates it) — querying or deleting from a non-existent MongoDB collection is a graceful no-op. `delete_many` on empty/non-existent collection returns without error.

### Route: HTTP 204 No Content, No Response Body

```python
@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_route(...) -> None:
```

FastAPI with `status_code=204` and `-> None` return type automatically suppresses response body. Do NOT return anything from this route (not even `None` explicitly).

### 404-Before-403 Authorization Pattern

Consistent with `get_agent()` and `update_agent_config()`:
1. `find_one({"agent_id": agent_id})` — fetch without tenant filter
2. If `None` → `AgentNotFoundError` (404)
3. If `doc["tenant_id"] != tenant_id` → `ForbiddenError` (403)

NEVER reverse this order — reversing leaks existence info to attackers.

### `get_vector_store` Raises `ProviderUnavailableError` (503) for Unknown Providers

`app/core/dependencies.py:get_vector_store` raises `ProviderUnavailableError` if the vector store key is not in `VECTOR_STORE_REGISTRY`. At Epic 2 stage, `VECTOR_STORE_REGISTRY` is empty — so in production, any deletion attempt will currently raise 503. This is expected and correct behavior for this sprint; providers are wired in Epic 4+.

**DO NOT add a try/catch to suppress this error.** It must propagate so the caller knows the operation failed. This is documented in `_bmad-output/implementation-artifacts/2-2-tenant-listing-and-deletion.md:191`.

In tests, always `patch("app.services.agent_service.get_vector_store", return_value=mock_vs)` to bypass the empty registry.

### `make_mock_db` and `make_authed_app` Extensions Are Backward-Compatible

Both functions already support multi-collection dispatch (agents/documents/tenants) from story 2.5. Adding `delete_one` and `delete_many` as new `AsyncMock` attributes does NOT break any existing tests — existing tests never assert on these methods.

**Critical:** The mock_db `__getitem__` dispatch already routes `"documents"` to `mock_documents` — no changes needed to the dispatch function itself.

### Import Addition to `agent_service.py`

Add `from app.core.dependencies import get_vector_store` to the imports. Check ruff I001 order — `app.core.dependencies` comes before `app.core.errors` alphabetically:

```python
from app.core.dependencies import get_vector_store
from app.core.errors import (
    AgentAlreadyExistsError,
    AgentConfigInvalidError,
    AgentNotFoundError,
    ForbiddenError,
)
```

### Previously Established Patterns (Must Follow)

- `from datetime import UTC` then `datetime.now(UTC)` — NEVER `datetime.utcnow()`
- Built-in generics: `list[X]`, `dict[K, V]` — NOT `List`, `Dict`
- `X | None` — NOT `Optional[X]`
- Never `print()` or `import logging` — always `get_logger(__name__)` from `app/utils/observability.py`
- ruff I001 import order: stdlib → third-party → first-party
- Never raise `HTTPException` in services — raise typed `TrueRAGError` subclasses only
- Never hardcode error codes as strings — use `ErrorCode` enum (though no new error codes needed here)
- 205 passing tests as baseline — all must still pass after this story

### No New Error Classes or Model Classes Needed

All required errors (`AgentNotFoundError`, `ForbiddenError`) already exist in `app/core/errors.py`.
No new Pydantic models needed — DELETE returns 204 with no body.

### Files to Modify (No New Files)

```
app/
├── services/agent_service.py     ← ADD: delete_agent(); import get_vector_store
└── api/v1/agents.py              ← ADD: DELETE /{agent_id} route

tests/
├── api/v1/test_agents.py         ← EXTEND: make_authed_app (delete mocks) + 4 DELETE tests
└── services/test_agent_service.py ← EXTEND: make_mock_db (delete mocks) + 6 delete tests
```

### Project Structure Notes

- All agent routes stay in `app/api/v1/agents.py` — no new route files
- No changes to `app/main.py`, `app/core/errors.py`, `app/core/auth.py`, `app/models/agent.py`
- `documents` collection deletion is a cascade side-effect; collection created in Epic 3

### References

- [Source: epics.md#Story 2.6] — User story and all acceptance criteria (FR9)
- [Source: architecture.md#D8] — Namespace format: `{tenant_id}_{agent_id}`
- [Source: app/services/tenant_service.py:98-121] — `delete_tenant()` — direct pattern to follow for vector store cleanup
- [Source: app/core/dependencies.py:get_vector_store] — raises `ProviderUnavailableError` for unknown providers
- [Source: app/interfaces/vector_store.py:16] — `delete_namespace(namespace: str) -> None` abstract method
- [Source: app/core/errors.py] — `AgentNotFoundError` (404), `ForbiddenError` (403)
- [Source: app/api/v1/agents.py] — existing route patterns; `status.HTTP_204_NO_CONTENT` usage
- [Source: story 2.5 dev notes] — 404-before-403 pattern; `make_mock_db` / `make_authed_app` structure; 205 test baseline
- [Source: tests/services/test_tenant_service.py:249-273] — `patch("...get_vector_store", ...)` mocking pattern

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- Added `delete_agent()` to `agent_service.py` following exact `delete_tenant` pattern: documents → agent → vector namespace deletion order
- Added `from app.core.dependencies import get_vector_store` import (ruff I001-compliant order)
- Added `DELETE /{agent_id}` route to `agents.py` returning HTTP 204 No Content
- Extended `make_mock_db` and `make_authed_app` with `delete_one`/`delete_many` AsyncMock — backward-compatible
- 14 new tests added (6 service + 4 API + 4 pre-existing checks); 219 total passing
- ruff, mypy --strict, pytest all exit 0

### File List

- app/services/agent_service.py
- app/api/v1/agents.py
- tests/services/test_agent_service.py
- tests/api/v1/test_agents.py

## Change Log

- 2026-04-26: Implemented agent deletion — `delete_agent()` service, `DELETE /{agent_id}` route, cascade document delete, vector namespace cleanup; 14 new tests (219 total passing)
