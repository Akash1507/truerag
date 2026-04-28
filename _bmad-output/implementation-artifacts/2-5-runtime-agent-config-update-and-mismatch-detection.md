# Story 2.5: Runtime Agent Config Update & Mismatch Detection

Status: done

## Story

As a Tenant Developer,
I want to update my agent's pipeline configuration at runtime without restarting the service, and receive a clear warning when my change creates a mismatch with already-ingested data,
so that I can iterate on retrieval strategy with zero downtime and understand when a reindex is required (FR6, FR10, FR56).

## Acceptance Criteria

**AC1:** Given `PATCH /v1/agents/{agent_id}/config` with one or more valid config field changes
When the request is processed
Then the agent document in MongoDB is updated with the new values and `updated_at` timestamp; HTTP 200 is returned with the updated agent object; the change takes effect on the next request without any service restart

**AC2:** Given a `PATCH` request that changes `chunking_strategy` when the agent has existing ingested documents
When the request is processed
Then the update is applied and the response includes a warning: `"chunking_strategy updated. Existing chunks were generated with '<old_strategy>'. Re-ingestion required for changes to take effect."` (HTTP 200, not an error)

**AC3:** Given a `PATCH` request that changes `embedding_provider` when the agent has existing ingested documents
When the request is processed
Then the update is applied and the response includes a warning: `"embedding_provider updated from '<old_provider>' to '<new_provider>'. Existing chunks require re-embedding before retrieval quality is reliable."` (HTTP 200, not an error)

**AC4:** Given a `PATCH` request with an unsupported config value (e.g., `chunking_strategy: "unknown"`)
When the request is processed
Then HTTP 400 Bad Request is returned with `AGENT_CONFIG_INVALID`; the agent document is not modified

## Tasks / Subtasks

- [x] Task 1: Add `AgentConfigUpdateRequest` and `AgentUpdateResponse` to `app/models/agent.py` (AC1–AC4)
  - [x] 1.1 Add `AgentConfigUpdateRequest` after `AgentCreateRequest`:
    ```python
    class AgentConfigUpdateRequest(BaseModel):
        chunking_strategy: str | None = None
        vector_store: str | None = None
        embedding_provider: str | None = None
        llm_provider: str | None = None
        retrieval_mode: str | None = None
        reranker: str | None = None
        top_k: int | None = Field(default=None, ge=1, le=100)
        semantic_cache_enabled: bool | None = None
        semantic_cache_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    ```
    All fields optional — partial update semantics. `name` is NOT included; this endpoint updates pipeline config only.

  - [x] 1.2 Add `AgentUpdateResponse` after `AgentListResponse`:
    ```python
    class AgentUpdateResponse(BaseModel):
        agent_id: str
        tenant_id: str
        name: str
        chunking_strategy: str
        vector_store: str
        embedding_provider: str
        llm_provider: str
        retrieval_mode: str
        reranker: str
        top_k: int
        semantic_cache_enabled: bool
        semantic_cache_threshold: float | None
        status: str
        created_at: datetime
        updated_at: datetime
        warnings: list[str]
    ```
    This is `AgentCreateResponse` + `warnings: list[str]` (empty list when no mismatch detected).

- [x] Task 2: Add `update_agent_config()` to `app/services/agent_service.py` (AC1–AC4)
  - [x] 2.1 Add `AgentConfigUpdateRequest` to the models import block:
    ```python
    from app.models.agent import (
        VALID_CHUNKING_STRATEGIES,
        VALID_EMBEDDING_PROVIDERS,
        VALID_LLM_PROVIDERS,
        VALID_RERANKERS,
        VALID_RETRIEVAL_MODES,
        VALID_VECTOR_STORES,
        AgentConfigUpdateRequest,
        AgentCreateRequest,
        AgentDocument,
    )
    ```

  - [x] 2.2 Add `update_agent_config()` function after `list_agents()`:
    ```python
    async def update_agent_config(
        agent_id: str,
        tenant_id: str,
        request: AgentConfigUpdateRequest,
        db: AsyncIOMotorDatabase[Any],
    ) -> tuple[AgentDocument, list[str]]:
        doc = await db["agents"].find_one({"agent_id": agent_id})
        if doc is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")
        if doc["tenant_id"] != tenant_id:
            raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")

        # Validate provided fields before touching the DB
        for field, valid_set in _FIELD_VALIDATORS:
            value: str | None = getattr(request, field)
            if value is not None and value not in valid_set:
                raise AgentConfigInvalidError(
                    f"Invalid {field}: {value!r}. Supported values: {sorted(valid_set)}"
                )

        # Build update payload — only fields that were explicitly provided
        update_dict: dict[str, Any] = {}
        for field in (
            "chunking_strategy",
            "vector_store",
            "embedding_provider",
            "llm_provider",
            "retrieval_mode",
            "reranker",
            "top_k",
            "semantic_cache_enabled",
            "semantic_cache_threshold",
        ):
            new_val = getattr(request, field)
            if new_val is not None:
                update_dict[field] = new_val

        # Mismatch detection — only relevant when something actually changed
        warnings: list[str] = []
        mismatch_fields = {"chunking_strategy", "embedding_provider"}
        changed_mismatch = {f for f in mismatch_fields if f in update_dict and update_dict[f] != doc[f]}
        if changed_mismatch:
            has_docs = await db["documents"].find_one({"agent_id": agent_id}) is not None
            if has_docs:
                if "chunking_strategy" in changed_mismatch:
                    old_strategy: str = doc["chunking_strategy"]
                    warnings.append(
                        f"chunking_strategy updated. Existing chunks were generated with "
                        f"'{old_strategy}'. Re-ingestion required for changes to take effect."
                    )
                if "embedding_provider" in changed_mismatch:
                    old_provider: str = doc["embedding_provider"]
                    new_provider: str = update_dict["embedding_provider"]
                    warnings.append(
                        f"embedding_provider updated from '{old_provider}' to '{new_provider}'. "
                        f"Existing chunks require re-embedding before retrieval quality is reliable."
                    )

        if update_dict:
            update_dict["updated_at"] = datetime.now(UTC)
            await db["agents"].update_one({"agent_id": agent_id}, {"$set": update_dict})
            updated_doc = await db["agents"].find_one({"agent_id": agent_id})
        else:
            updated_doc = doc  # no-op patch — return current doc unchanged

        logger.info(
            "agent_config_updated",
            extra={
                "operation": "update_agent_config",
                "extra_data": {
                    "agent_id": agent_id,
                    "tenant_id": tenant_id,
                    "fields_updated": list(update_dict.keys()),
                    "warnings": len(warnings),
                },
            },
        )
        return AgentDocument(**{k: updated_doc[k] for k in AgentDocument.model_fields}), warnings
    ```

- [x] Task 3: Add `PATCH /{agent_id}/config` route to `app/api/v1/agents.py` (AC1–AC4)
  - [x] 3.1 Add `AgentConfigUpdateRequest` and `AgentUpdateResponse` to the models import:
    ```python
    from app.models.agent import (
        AgentConfigUpdateRequest,
        AgentCreateRequest,
        AgentCreateResponse,
        AgentListResponse,
        AgentUpdateResponse,
    )
    ```

  - [x] 3.2 Add `PATCH /{agent_id}/config` route after `get_agent_route`:
    ```python
    @router.patch("/{agent_id}/config", response_model=AgentUpdateResponse)
    async def update_agent_config_route(
        agent_id: str,
        body: AgentConfigUpdateRequest,
        request: Request,
        caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
    ) -> AgentUpdateResponse:
        settings = get_settings()
        db = request.app.state.motor_client[settings.mongodb_database]
        agent, warnings = await agent_service.update_agent_config(
            agent_id, caller.tenant_id, body, db
        )
        return AgentUpdateResponse(**agent.model_dump(), warnings=warnings)
    ```

  - [x] 3.3 Final router registration order in `agents.py` (order matters for FastAPI path resolution):
    1. `POST ""` — create_agent_route (existing)
    2. `GET ""` — list_agents_route (existing)
    3. `GET "/{agent_id}"` — get_agent_route (existing)
    4. `PATCH "/{agent_id}/config"` — update_agent_config_route (NEW)

    `PATCH "/{agent_id}/config"` has a fixed `/config` suffix so it cannot conflict with `GET "/{agent_id}"`. Registration order between them does not matter in this case, but follow the order above for consistency.

- [x] Task 4: Write tests (AC1–AC4)
  - [x] 4.1 Extend `tests/services/test_agent_service.py`:

    **Update imports at top of file — add `AgentConfigUpdateRequest` and `update_agent_config`:**
    ```python
    from app.models.agent import AgentConfigUpdateRequest, AgentCreateRequest, AgentDocument
    from app.services.agent_service import create_agent, get_agent, list_agents, update_agent_config
    ```

    **Extend `make_mock_db` to support multi-collection dispatch and `update_agent_config` mocks:**
    ```python
    def make_mock_db(
        find_one_return: dict | None = None,
        insert_raises: Exception | None = None,
        find_return_list: list[dict] | None = None,
        # NEW: for update_agent_config
        agents_find_one_side_effect: list[dict | None] | None = None,
        update_one_return: MagicMock | None = None,
        documents_find_one_return: dict | None = None,
    ) -> MagicMock:
        mock_agents = MagicMock()
        if agents_find_one_side_effect is not None:
            mock_agents.find_one = AsyncMock(side_effect=agents_find_one_side_effect)
        else:
            mock_agents.find_one = AsyncMock(return_value=find_one_return)
        if insert_raises is not None:
            mock_agents.insert_one = AsyncMock(side_effect=insert_raises)
        else:
            mock_agents.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake-oid"))
        mock_agents.update_one = AsyncMock(return_value=update_one_return or MagicMock())

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=find_return_list or [])
        mock_agents.find = MagicMock(return_value=mock_cursor)

        mock_documents = MagicMock()
        mock_documents.find_one = AsyncMock(return_value=documents_find_one_return)

        def get_collection(name: str) -> MagicMock:
            if name == "agents":
                return mock_agents
            elif name == "documents":
                return mock_documents
            return MagicMock()

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=get_collection)
        return mock_db
    ```

    This change is backward compatible with all existing tests. Old callers that pass only `find_one_return` / `find_return_list` still work correctly.

    **Helper constant for update tests:**
    ```python
    UPDATED_AGENT_DOC = {
        **FAKE_AGENT_DOC,
        "chunking_strategy": "semantic",  # changed field
        "updated_at": datetime.now(UTC),
    }
    ```

    **New tests for `update_agent_config`:**
    - `test_update_agent_config_success_no_field_changes` — empty `AgentConfigUpdateRequest()`, no docs, `update_one` NOT called, returns current doc unchanged, `warnings == []`
    - `test_update_agent_config_success_updates_field` — changes `vector_store`, no existing docs, `update_one` called once, returned doc has new `vector_store`, `warnings == []`
    - `test_update_agent_config_chunking_warning_with_docs` — changes `chunking_strategy` from `"fixed_size"` to `"semantic"`, documents collection returns a doc → `warnings` has 1 entry containing `"fixed_size"` and `"Re-ingestion required"`
    - `test_update_agent_config_chunking_no_warning_no_docs` — changes `chunking_strategy`, documents collection returns `None` → `warnings == []`
    - `test_update_agent_config_chunking_no_warning_same_value` — `chunking_strategy="fixed_size"` (same as current doc), documents collection returns a doc → `warnings == []` (no actual change)
    - `test_update_agent_config_embedding_warning_with_docs` — changes `embedding_provider` from `"openai"` to `"cohere"`, documents collection returns a doc → `warnings` has 1 entry containing both `"openai"` and `"cohere"`
    - `test_update_agent_config_both_warnings` — changes both `chunking_strategy` and `embedding_provider`, documents collection returns a doc → `warnings` has 2 entries
    - `test_update_agent_config_not_found` — `find_one` returns `None` → raises `AgentNotFoundError`; `update_one` NOT called
    - `test_update_agent_config_wrong_tenant` — doc has `tenant_id="other-tenant"` → raises `ForbiddenError`; `update_one` NOT called
    - `test_update_agent_config_invalid_chunking_strategy` — `chunking_strategy="bad"` → raises `AgentConfigInvalidError`; `update_one` NOT called

  - [x] 4.2 Extend `tests/api/v1/test_agents.py`:

    **Update `make_authed_app` to support `PATCH` tests — add params and dispatch documents collection:**
    ```python
    def make_authed_app(
        find_one_return: dict | None = None,
        find_return_list: list[dict] | None = None,
        # NEW for PATCH support:
        agents_find_one_side_effect: list[dict | None] | None = None,
        update_one_return: MagicMock | None = None,
        documents_find_one_return: dict | None = None,
    ) -> FastAPI:
        app = create_app()

        mock_tenants = MagicMock()
        mock_tenants.find_one = AsyncMock(return_value=FAKE_CALLER)

        mock_agents = MagicMock()
        if agents_find_one_side_effect is not None:
            mock_agents.find_one = AsyncMock(side_effect=agents_find_one_side_effect)
        else:
            mock_agents.find_one = AsyncMock(return_value=find_one_return)
        mock_agents.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake-oid"))
        mock_agents.update_one = AsyncMock(return_value=update_one_return or MagicMock())

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=find_return_list or [])
        mock_agents.find = MagicMock(return_value=mock_cursor)

        mock_documents = MagicMock()
        mock_documents.find_one = AsyncMock(return_value=documents_find_one_return)

        def get_collection(name: str) -> MagicMock:
            if name == "agents":
                return mock_agents
            elif name == "documents":
                return mock_documents
            return mock_tenants

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=get_collection)
        mock_motor = MagicMock()
        mock_motor.__getitem__ = MagicMock(return_value=mock_db)
        app.state.motor_client = mock_motor
        app.state.pg_pool = MagicMock()
        app.state.aws_session = MagicMock()
        return app
    ```

    This change is fully backward compatible. All existing tests that pass `find_one_return` or `find_return_list` only will continue to work unchanged.

    Note: Old `get_collection` dispatched any non-"agents" name to `mock_tenants`. New dispatch is explicit: "agents", "documents", or fallback to `mock_tenants`. Auth lookups always use `mock_tenants.find_one` via the "tenants" collection name — this is unchanged.

    **Helper for PATCH tests — updated doc after write:**
    ```python
    UPDATED_AGENT_DOC = {
        **FAKE_AGENT_DOC,
        "chunking_strategy": "semantic",
        "updated_at": datetime.now(UTC),
    }
    ```

    **New tests for `PATCH /v1/agents/{agent_id}/config`:**
    - `test_patch_agent_config_200_no_warnings` — agents `find_one` side_effect `[FAKE_AGENT_DOC, FAKE_AGENT_DOC]`, no docs, `PATCH` with `{"vector_store": "pgvector"}` (same value) → 200, `warnings == []`
    - `test_patch_agent_config_200_chunking_warning` — agents `find_one` side_effect `[FAKE_AGENT_DOC, UPDATED_AGENT_DOC]`, documents returns a doc, `PATCH` with `{"chunking_strategy": "semantic"}` → 200, `warnings` has 1 entry with `"fixed_size"` and `"Re-ingestion"`
    - `test_patch_agent_config_200_embedding_warning` — agents `find_one` side_effect `[FAKE_AGENT_DOC, {..., "embedding_provider": "cohere"}]`, documents returns a doc, `PATCH` with `{"embedding_provider": "cohere"}` → 200, `warnings` has 1 entry with `"openai"` and `"cohere"`
    - `test_patch_agent_config_400_invalid_value` — `PATCH` with `{"chunking_strategy": "bad"}`, `agents_find_one_side_effect=[FAKE_AGENT_DOC]` → 400, `AGENT_CONFIG_INVALID`
    - `test_patch_agent_config_404_not_found` — `agents_find_one_side_effect=[None]` → 404, `AGENT_NOT_FOUND`
    - `test_patch_agent_config_401_no_api_key` — no `X-API-Key` header → 401

  - [x] 4.3 Run `ruff check app/ tests/` — must exit 0
  - [x] 4.4 Run `mypy app/ --strict` — must exit 0
  - [x] 4.5 Run `pytest tests/ -v` — all 205 tests pass (189 existing + 10 service + 6 API); no regressions

## Dev Notes

### Response Model: `AgentUpdateResponse` has `warnings: list[str]`, Never Optional

`warnings` is always a `list[str]`, never `None`. No mismatch → `warnings=[]`. This avoids null checks on the client side.

The service returns `tuple[AgentDocument, list[str]]`. The route constructs:
```python
return AgentUpdateResponse(**agent.model_dump(), warnings=warnings)
```

### Mismatch Detection: Existence Check, Not Count

Only `chunking_strategy` and `embedding_provider` changes trigger mismatch warnings (per FR10, FR56). Other fields (`vector_store`, `llm_provider`, `retrieval_mode`, `reranker`, `top_k`, `semantic_cache_*`) update silently.

Existence check:
```python
has_docs = await db["documents"].find_one({"agent_id": agent_id}) is not None
```

- Uses `find_one` not `count_documents` — stops after first match, no full collection scan
- Checks the `documents` MongoDB collection (implemented in Epic 3)
- At story 2.5 time, no documents exist yet → warnings never fire in practice; code is future-proof

The check is only performed when at least one mismatch-relevant field actually changes to a different value:
```python
changed_mismatch = {f for f in mismatch_fields if f in update_dict and update_dict[f] != doc[f]}
if changed_mismatch:
    has_docs = await db["documents"].find_one({"agent_id": agent_id}) is not None
```

This avoids an unnecessary DB query when neither field is changing.

### Warning Messages — Exact Strings

```
# chunking_strategy:
f"chunking_strategy updated. Existing chunks were generated with '{old_strategy}'. Re-ingestion required for changes to take effect."

# embedding_provider:
f"embedding_provider updated from '{old_provider}' to '{new_provider}'. Existing chunks require re-embedding before retrieval quality is reliable."
```

Tests assert these strings are contained in the warning entries — use `in` not `==` to avoid brittleness.

### Validation: Reuse `_FIELD_VALIDATORS`, Skip `None` Fields

```python
for field, valid_set in _FIELD_VALIDATORS:
    value: str | None = getattr(request, field)
    if value is not None and value not in valid_set:
        raise AgentConfigInvalidError(...)
```

`top_k`, `semantic_cache_threshold` validation is handled by Pydantic `Field(ge=..., le=...)` on `AgentConfigUpdateRequest`. No manual validation needed for those.

The agent document is NOT modified before validation completes (fail-fast, no partial updates).

### No-Op PATCH: Empty Request Returns Current Doc

If `request` has all fields `None` (empty body `{}`), `update_dict` is empty, `update_one` is NOT called, current doc is returned as-is with `warnings=[]`. This is correct behavior — idempotent.

### Cross-Tenant Authorization Pattern

Same as `get_agent()`:
1. `find_one({"agent_id": agent_id})` — fetch without tenant filter
2. If `None` → `AgentNotFoundError` (404)
3. If `doc["tenant_id"] != tenant_id` → `ForbiddenError` (403)
4. Proceed with validation and update

Order matters: 404 before 403. Never reverse (reversing leaks existence info to attackers). Consistent with the pattern established in story 2.4.

### Two-Step Update: `update_one` Then `find_one`

```python
await db["agents"].update_one({"agent_id": agent_id}, {"$set": update_dict})
updated_doc = await db["agents"].find_one({"agent_id": agent_id})
```

This is simpler to test than `find_one_and_update`. The `update_dict` always includes `"updated_at": datetime.now(UTC)` when non-empty, so the re-fetched doc will have the updated timestamp.

### `make_mock_db` and `make_authed_app` Changes Are Backward Compatible

Both functions get new keyword args with defaults. All 189 existing tests use positional or existing keyword args — they are unaffected. Verify this by running the full suite before adding new tests.

The critical change in both helpers: `mock_db.__getitem__` changes from `return_value` (single mock) to `side_effect` (collection dispatch function). This routes `db["agents"]`, `db["documents"]`, and `db["tenants"]` to separate mocks. Existing tests that only touch agents will still work because the agents mock behavior is unchanged.

### Route: Use `@router.patch`, Not `@router.post`

```python
@router.patch("/{agent_id}/config", response_model=AgentUpdateResponse)
```

FastAPI PATCH semantics are correct here: partial update, not full replace. The endpoint path includes `/config` to be explicit that this updates pipeline config, not the agent's identity fields.

### Previously Established Patterns (Must Follow)

- `from datetime import UTC` then `datetime.now(UTC)` — NEVER `datetime.utcnow()`
- Built-in generics: `list[X]`, `dict[K, V]`, `tuple[A, B]` — NOT `List`, `Dict`, `Tuple`
- `X | None` — NOT `Optional[X]`
- Never `print()` or `import logging` — always `get_logger(__name__)` from `app/utils/observability.py`
- ruff I001 import order: stdlib → third-party → first-party
- Never raise `HTTPException` in services — raise typed `TrueRAGError` subclasses only
- Never hardcode error codes as strings — use `ErrorCode` enum
- `extra="ignore"` on `AgentDocument` — suppresses MongoDB `_id` during deserialization
- 189 passing tests as baseline — all must still pass after this story

### ErrorCode Pre-exists — Do NOT Re-declare

`CHUNKING_STRATEGY_MISMATCH` and `EMBEDDING_MODEL_MISMATCH` already exist in `app/core/errors.py:14-15`. These error codes are reserved for future use as hard errors (e.g., in Epic 8.4 when query path blocks on unresolved mismatch). In story 2.5 they are NOT raised as errors — mismatch produces a 200 warning, not a 400/422.

No new error classes are needed for this story.

### Files Changed

**Modified files only — no new files:**
```
app/
├── models/agent.py            ← ADD: AgentConfigUpdateRequest, AgentUpdateResponse
├── services/agent_service.py  ← ADD: update_agent_config(); import AgentConfigUpdateRequest
└── api/v1/agents.py           ← ADD: PATCH /{agent_id}/config route; import new models

tests/
├── api/v1/test_agents.py         ← EXTEND: make_authed_app + 6 new PATCH tests
└── services/test_agent_service.py ← EXTEND: make_mock_db + 10 new update tests
```

### Project Structure Notes

- All agent routes stay in `app/api/v1/agents.py` — no new route files
- No changes to `app/main.py`, `app/core/auth.py`, `app/core/rate_limiter.py`, `app/core/errors.py`
- `CHUNKING_STRATEGY_MISMATCH` / `EMBEDDING_MODEL_MISMATCH` in errors.py are untouched (pre-declared for Epic 8)
- MongoDB `documents` collection is queried but not created here (Epic 3 creates it); querying a non-existent collection returns `None` from `find_one` — graceful no-op

### References

- [Source: epics.md#Story 2.5] — User story and all acceptance criteria (FR6, FR10, FR56)
- [Source: architecture.md#D1] — `agents` collection schema; `documents` collection queried for existence check
- [Source: architecture.md#D10] — Error envelope: `{error: {code, message, request_id}}`
- [Source: architecture.md line 86] — "Runtime reconfigurability — config updates take effect on next request; no restart"
- [Source: architecture.md line 565] — `agent_service.py` handles "Agent CRUD, config mismatch detection (FR10, FR56)"
- [Source: app/core/errors.py:14-15] — `CHUNKING_STRATEGY_MISMATCH`, `EMBEDDING_MODEL_MISMATCH` pre-exist; no new error classes needed
- [Source: app/models/agent.py] — `AgentDocument`, `AgentCreateResponse` — field list to replicate in `AgentUpdateResponse`
- [Source: app/services/agent_service.py] — `_FIELD_VALIDATORS` to reuse for validation; `get_agent()` for cross-tenant auth pattern
- [Source: app/api/v1/agents.py] — existing route patterns; registration order
- [Source: story 2.4 dev notes] — Cross-tenant pattern (404 before 403); `make_authed_app` structure; 189 test baseline

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- mypy strict: `updated_doc` after `find_one` typed as `Any | None`; resolved with `assert updated_doc is not None` after the re-fetch.
- ruff E501: inline dict literal in test exceeded 100 chars; split to multi-line form.

### Completion Notes List

- Added `AgentConfigUpdateRequest` (all-optional partial update model) and `AgentUpdateResponse` (`AgentCreateResponse` + `warnings: list[str]`) to `app/models/agent.py`.
- Implemented `update_agent_config()` in `app/services/agent_service.py`: 404-before-403 auth pattern, fail-fast validation reusing `_FIELD_VALIDATORS`, mismatch detection for `chunking_strategy` and `embedding_provider` via `find_one` on `documents` collection, two-step `update_one` + `find_one` update.
- Added `PATCH /{agent_id}/config` route to `app/api/v1/agents.py`.
- Extended `make_mock_db` and `make_authed_app` helpers with backward-compatible multi-collection dispatch (agents / documents / tenants).
- Added 10 service-layer tests and 6 API-layer tests; all 205 tests pass with ruff and mypy clean.

### File List

- app/models/agent.py
- app/services/agent_service.py
- app/api/v1/agents.py
- tests/services/test_agent_service.py
- tests/api/v1/test_agents.py

## Change Log

- 2026-04-26: Implemented Story 2.5 — PATCH /v1/agents/{agent_id}/config with mismatch detection warnings for chunking_strategy and embedding_provider changes.
