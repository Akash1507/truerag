# Story 2.3: RAG Agent Creation with Full Pipeline Configuration

Status: done

## Story

As a Tenant Developer,
I want to create a named RAG Agent with a complete pipeline configuration specifying chunking strategy, vector store, embedding provider, LLM provider, retrieval mode, reranker, and top-k,
so that my agent's retrieval pipeline is fully defined from day one and all config fields are validated against supported values (FR5, FR21–27).

## Acceptance Criteria

**AC1:** Given `POST /v1/agents` with a valid config block (name, chunking_strategy, vector_store, embedding_provider, llm_provider, retrieval_mode, reranker, top_k)
When the request is processed
Then an agent document is created in the `agents` MongoDB collection with all config fields, `agent_id`, `tenant_id`, `status: "active"`, `created_at`, `updated_at`; HTTP 201 is returned with the full agent object

**AC2:** Given a config block with an unsupported value for any pipeline field (e.g. `chunking_strategy: "unknown"`)
When the request is processed
Then HTTP 400 Bad Request is returned with `AGENT_CONFIG_INVALID` code, listing the invalid field name and supported values; no agent document is created

**AC3:** Given a `POST /v1/agents` request where the name is already used by the same tenant
When the request is processed
Then HTTP 409 Conflict is returned with `AGENT_ALREADY_EXISTS` code; no duplicate agent document is created

**AC4:** Given a `POST /v1/agents` request body that includes an optional `tenant_id` field whose value does not match the authenticated caller's `tenant_id`
When the request is processed
Then HTTP 403 Forbidden is returned with `FORBIDDEN` code; no agent document is created

## Tasks / Subtasks

- [x] Task 1: Add new error codes and exceptions to `app/core/errors.py` (AC2, AC3)
  - [x] 1.1 Add `AGENT_CONFIG_INVALID = "AGENT_CONFIG_INVALID"` to `ErrorCode(StrEnum)`
  - [x] 1.2 Add `AGENT_ALREADY_EXISTS = "AGENT_ALREADY_EXISTS"` to `ErrorCode(StrEnum)`
  - [x] 1.3 Add `AgentConfigInvalidError(TrueRAGError)` — `code=ErrorCode.AGENT_CONFIG_INVALID`, `http_status=400`, default message `"Invalid agent configuration"`
  - [x] 1.4 Add `AgentAlreadyExistsError(TrueRAGError)` — `code=ErrorCode.AGENT_ALREADY_EXISTS`, `http_status=409`, default message `"Agent already exists"`

- [x] Task 2: Create `app/models/agent.py` (AC1, AC2)
  - [x] 2.1 Define allowed-value constants as `frozenset[str]` — validated in service, documented here as the source of truth:
    ```python
    VALID_CHUNKING_STRATEGIES: frozenset[str] = frozenset({"fixed_size", "semantic", "hierarchical", "document_aware"})
    VALID_VECTOR_STORES: frozenset[str] = frozenset({"pgvector", "qdrant", "pinecone"})
    VALID_EMBEDDING_PROVIDERS: frozenset[str] = frozenset({"openai", "cohere", "bedrock"})
    VALID_LLM_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai", "bedrock"})
    VALID_RETRIEVAL_MODES: frozenset[str] = frozenset({"dense", "sparse", "hybrid"})
    VALID_RERANKERS: frozenset[str] = frozenset({"none", "cross_encoder", "cohere"})
    ```
    These are the config schema definitions (FR21–FR27). Actual provider implementations come in Epic 4+. Do NOT validate via registry lookup — registries are mostly empty until Epic 4.

  - [ ] 2.2 Define `AgentDocument(BaseModel)` with `model_config = ConfigDict(populate_by_name=True, extra="ignore")`:
    ```python
    class AgentDocument(BaseModel):
        model_config = ConfigDict(populate_by_name=True, extra="ignore")
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
    ```
    The `extra="ignore"` is consistent with `TenantDocument` — prevents Pydantic errors when `_id` is present in a raw MongoDB doc.

  - [x] 2.2 Define `AgentDocument(BaseModel)` with `model_config = ConfigDict(populate_by_name=True, extra="ignore")`
  - [x] 2.3 Define `AgentCreateRequest(BaseModel)`:
    ```python
    AgentName = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True, pattern=r"^[a-zA-Z0-9_-]+$")]

    class AgentCreateRequest(BaseModel):
        name: AgentName
        chunking_strategy: str
        vector_store: str
        embedding_provider: str
        llm_provider: str
        retrieval_mode: str
        reranker: str
        top_k: int = Field(ge=1, le=100)
        tenant_id: str | None = None          # optional; if provided, must match caller — AC4
        semantic_cache_enabled: bool = False
        semantic_cache_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    ```
    All pipeline string fields are `str` (not `Literal` types) — validated in the service against the `VALID_*` frozensets, which produces a structured 400 error (not FastAPI's 422). This is intentional to satisfy AC2's requirement of a human-readable error listing the invalid field and supported values.

  - [x] 2.4 Define `AgentCreateResponse(BaseModel)` — mirrors `AgentDocument` exactly; serves as the 201 response schema:
    ```python
    class AgentCreateResponse(BaseModel):
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
    ```

- [x] Task 3: Create `app/services/agent_service.py` with `create_agent()` (AC1, AC2, AC3)
  - [x] 3.1 Imports — follow existing service patterns exactly:
    ```python
    from datetime import UTC, datetime
    from typing import Any
    from bson import ObjectId
    from motor.motor_asyncio import AsyncIOMotorDatabase
    from pymongo.errors import DuplicateKeyError
    from app.core.errors import AgentAlreadyExistsError, AgentConfigInvalidError
    from app.models.agent import (AgentCreateRequest, AgentDocument,
        VALID_CHUNKING_STRATEGIES, VALID_VECTOR_STORES, VALID_EMBEDDING_PROVIDERS,
        VALID_LLM_PROVIDERS, VALID_RETRIEVAL_MODES, VALID_RERANKERS)
    from app.utils.observability import get_logger
    ```
  - [x] 3.2 Validation loop — validate all six config string fields before touching the database:
    ```python
    _FIELD_VALIDATORS: list[tuple[str, str, frozenset[str]]] = [
        ("chunking_strategy", request.chunking_strategy, VALID_CHUNKING_STRATEGIES),
        ("vector_store", request.vector_store, VALID_VECTOR_STORES),
        ("embedding_provider", request.embedding_provider, VALID_EMBEDDING_PROVIDERS),
        ("llm_provider", request.llm_provider, VALID_LLM_PROVIDERS),
        ("retrieval_mode", request.retrieval_mode, VALID_RETRIEVAL_MODES),
        ("reranker", request.reranker, VALID_RERANKERS),
    ]
    for field, value, valid_set in _FIELD_VALIDATORS:
        if value not in valid_set:
            raise AgentConfigInvalidError(
                f"Invalid {field}: {value!r}. Supported values: {sorted(valid_set)}"
            )
    ```
    Validation raises on the first invalid field. The error message is human-readable and includes the field name and supported values (AC2).

  - [x] 3.3 Duplicate name check (AC3): `await db["agents"].find_one({"tenant_id": tenant_id, "name": request.name})` → if not None, raise `AgentAlreadyExistsError(f"Agent with name '{request.name}' already exists for this tenant")`
  - [x] 3.4 Generate IDs and timestamps:
    ```python
    agent_id = str(ObjectId())
    now = datetime.now(UTC)
    ```
  - [x] 3.5 Build document dict and call `await db["agents"].insert_one(doc)` — wrap in `try/except DuplicateKeyError` as a DB-level backstop for the unique index (raises `AgentAlreadyExistsError`):
    ```python
    doc: dict[str, Any] = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "name": request.name,
        "chunking_strategy": request.chunking_strategy,
        "vector_store": request.vector_store,
        "embedding_provider": request.embedding_provider,
        "llm_provider": request.llm_provider,
        "retrieval_mode": request.retrieval_mode,
        "reranker": request.reranker,
        "top_k": request.top_k,
        "semantic_cache_enabled": request.semantic_cache_enabled,
        "semantic_cache_threshold": request.semantic_cache_threshold,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db["agents"].insert_one(doc)
    except DuplicateKeyError as exc:
        raise AgentAlreadyExistsError(...) from exc
    ```
  - [x] 3.6 Return `AgentDocument(**{k: doc[k] for k in AgentDocument.model_fields})`
  - [x] 3.7 Log at INFO: `operation="create_agent"`, `extra_data={"agent_id": agent_id, "tenant_id": tenant_id}`

- [x] Task 4: Add `POST /v1/agents` route to `app/api/v1/agents.py` (AC1–AC4)
  - [x] 4.1 Replace current stub with:
    ```python
    from fastapi import APIRouter, Depends, Request, status
    from app.core.auth import get_current_tenant
    from app.core.config import get_settings
    from app.core.errors import ForbiddenError
    from app.models.agent import AgentCreateRequest, AgentCreateResponse
    from app.models.tenant import TenantDocument
    from app.services import agent_service

    router = APIRouter()

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentCreateResponse)
    async def create_agent_route(
        body: AgentCreateRequest,
        request: Request,
        caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
    ) -> AgentCreateResponse:
        if body.tenant_id is not None and body.tenant_id != caller.tenant_id:
            raise ForbiddenError("Cannot create agent for a different tenant")
        settings = get_settings()
        db = request.app.state.motor_client[settings.mongodb_database]
        agent = await agent_service.create_agent(body, caller.tenant_id, db)
        return AgentCreateResponse(**agent.model_dump())
    ```
  - [x] 4.2 `POST /v1/agents` is auth-required — `AuthMiddleware` handles this; no changes to `SKIP_AUTH_PATHS`
  - [x] 4.3 The route uses `caller.tenant_id` (from auth) as the authoritative `tenant_id` — body's optional `tenant_id` is only checked for cross-tenant detection (AC4)

- [x] Task 5: Add MongoDB indexes for `agents` collection to `app/main.py` (AC1, AC3)
  - [x] 5.1 In the lifespan function, after `db["tenants"].create_index(...)`, add:
    ```python
    await db["agents"].create_index([("tenant_id", 1), ("name", 1)], unique=True)
    await db["agents"].create_index([("agent_id", 1)], unique=True)
    ```
  - [x] 5.2 The compound `(tenant_id, name)` unique index enforces AC3 at the DB level as a DuplicateKeyError backstop. The service-level `find_one` check is the primary guard; the index is a safety net.
  - [x] 5.3 The `agent_id` unique index supports fast lookup by `agent_id` for Stories 2.4–2.6.

- [x] Task 6: Write tests (AC1–AC4)
  - [x] 6.1 Create `tests/api/v1/test_agents.py`:
    - Define `FAKE_API_KEY`, `FAKE_CALLER`, and `make_authed_app_for_create(insert_result, find_one_return)` helper (mirrors `make_app_with_mock_db` pattern from `test_tenants.py`)
    - `test_create_agent_201_happy_path` — valid body → 201, response includes all agent fields, `status == "active"`, `tenant_id == caller's tenant_id` (not body's)
    - `test_create_agent_400_invalid_chunking_strategy` — `chunking_strategy: "unknown"` → 400, `error.code == "AGENT_CONFIG_INVALID"`, message mentions `chunking_strategy` and supported values
    - `test_create_agent_400_invalid_vector_store` — `vector_store: "redis"` → 400, `AGENT_CONFIG_INVALID`
    - `test_create_agent_400_invalid_embedding_provider` — `embedding_provider: "mistral"` → 400
    - `test_create_agent_409_duplicate_name` — mock `find_one` returns existing agent doc → 409, `AGENT_ALREADY_EXISTS`
    - `test_create_agent_403_mismatched_tenant_id` — body includes `tenant_id: "other-tenant"` while caller's `tenant_id == "caller-id"` → 403, `FORBIDDEN`
    - `test_create_agent_401_no_api_key` — no `X-API-Key` header → 401
    - `test_create_agent_body_tenant_id_matches_caller_is_accepted` — `body.tenant_id == caller.tenant_id` → 201 (not rejected)

  - [x] 6.2 Create `tests/services/test_agent_service.py`:
    - `test_create_agent_success` — mock DB (`find_one` returns None, `insert_one` succeeds) → returns `AgentDocument` with correct fields; `status == "active"`, `tenant_id == passed tenant_id`
    - `test_create_agent_invalid_chunking_strategy` — raises `AgentConfigInvalidError`; message contains `"chunking_strategy"` and supported values; DB not touched
    - `test_create_agent_invalid_vector_store` — raises `AgentConfigInvalidError`
    - `test_create_agent_invalid_llm_provider` — raises `AgentConfigInvalidError`
    - `test_create_agent_duplicate_name` — mock `find_one` returns an existing doc → raises `AgentAlreadyExistsError`; `insert_one` never called
    - `test_create_agent_duplicate_key_from_db` — mock `find_one` returns None but `insert_one` raises `DuplicateKeyError` → raises `AgentAlreadyExistsError`
    - `test_create_agent_config_error_message_format` — error message format `"Invalid {field}: '{value}'. Supported values: [...]"` verified

  - [x] 6.3 Run `ruff check app/ tests/` — must exit 0
  - [x] 6.4 Run `mypy app/ --strict` — must exit 0
  - [x] 6.5 Run `pytest tests/ -v` — all 154 existing tests pass + new tests pass; no regressions

## Dev Notes

### Schema — `agents` MongoDB Collection (D1)

Full document structure stored in MongoDB (`agents` collection):
```python
{
    "agent_id": "24-char hex str (ObjectId)",
    "tenant_id": "24-char hex str (ObjectId, from authenticated caller)",
    "name": "str (unique per tenant)",
    "chunking_strategy": "fixed_size | semantic | hierarchical | document_aware",
    "vector_store": "pgvector | qdrant | pinecone",
    "embedding_provider": "openai | cohere | bedrock",
    "llm_provider": "anthropic | openai | bedrock",
    "retrieval_mode": "dense | sparse | hybrid",
    "reranker": "none | cross_encoder | cohere",
    "top_k": "int (1–100)",
    "semantic_cache_enabled": "bool",
    "semantic_cache_threshold": "float | null",
    "status": "active",   # only valid value at creation
    "created_at": "datetime (UTC, timezone-aware)",
    "updated_at": "datetime (UTC, timezone-aware, = created_at at creation)"
}
```

**CRITICAL**: `agent_id` is stored as an explicit `str` field — NOT as an `_id` alias. Consistent with `tenant_id` in `tenants` collection. The MongoDB `_id` (auto-generated ObjectId) is separate from `agent_id`. This is by architectural design — `extra="ignore"` on `AgentDocument` suppresses `_id` during `model_validate`.

**Namespace format (D8)**: `{tenant_id}_{agent_id}` — both 24-char hex ObjectId strings. Always constructed as `f"{tenant_id}_{agent_id}"`. Never hardcoded or reconstructed differently. Used in Stories 2.6, 4.x for vector store namespace isolation.

### Validation: 400 NOT 422

FastAPI returns 422 for Pydantic validation errors. This story's AC2 requires **HTTP 400** with a structured `AGENT_CONFIG_INVALID` error. To achieve this:
- Pipeline config fields (`chunking_strategy`, `vector_store`, etc.) are declared as `str` in `AgentCreateRequest` — NOT `Literal` types
- Validation is performed manually in `agent_service.create_agent()` before any DB call
- Invalid config raises `AgentConfigInvalidError(http_status=400)` which is handled by the existing `truerag_exception_handler`
- The error message includes both the field name and sorted supported values: `"Invalid chunking_strategy: 'unknown'. Supported values: ['document_aware', 'fixed_size', 'hierarchical', 'semantic']"`

Do NOT change this to Pydantic `Literal` types — that changes the HTTP code to 422 and breaks AC2. FastAPI's automatic 422 for `name` (pattern/length violation) and `top_k` (range violation) is acceptable since those are structural request validations, not config-value validations.

### Why Not Validate via Registry Lookup?

`VECTOR_STORE_REGISTRY`, `CHUNKING_REGISTRY`, `EMBEDDING_REGISTRY`, `LLM_REGISTRY` are currently empty (populated in Epics 4–5). Validating config strings against the registry would reject ALL values right now. The `VALID_*` frozensets in `app/models/agent.py` are the authoritative config schema — they define what will be supported by the platform, independent of which backends are currently implemented.

### AC4 — Cross-Tenant Detection

The `POST /v1/agents` body includes an optional `tenant_id: str | None = None` field. If provided and it does not match the authenticated caller's `tenant_id`, the route raises `ForbiddenError` before calling the service. If not provided (the common case), `caller.tenant_id` from auth is used — cross-tenant writes are structurally impossible.

The route never passes `body.tenant_id` to the service — it always passes `caller.tenant_id`. This prevents any cross-tenant injection regardless of the body field.

### MongoDB Index Strategy

Two indexes on the `agents` collection (added to `app/main.py` lifespan):
1. `compound unique (tenant_id, name)` — enforces per-tenant name uniqueness at DB level (backstop for AC3 DuplicateKeyError)
2. `unique (agent_id)` — supports O(1) lookup by `agent_id` for Stories 2.4 `GET /v1/agents/{agent_id}` and 2.6 `DELETE /v1/agents/{agent_id}`

Index creation is idempotent — safe to run on every startup.

### `app/services/agent_service.py` — Service Signature

```python
async def create_agent(
    request: AgentCreateRequest,
    tenant_id: str,
    db: AsyncIOMotorDatabase[Any],
) -> AgentDocument:
```

`tenant_id` is passed separately from `request` (not `request.tenant_id`) — the service is unaware of the optional body field. Ownership is enforced at the API layer before calling this service.

### Previously Established Patterns (Must Follow)

- **`from datetime import UTC`** then `datetime.now(UTC)` — NEVER `datetime.utcnow()`
- **Built-in generics**: `list[X]`, `dict[K, V]`, `tuple[A, B]` — NOT `List`, `Dict`, `Tuple`
- **`X | None`** — NOT `Optional[X]`
- **Never `print()` or `import logging`** — always `get_logger(__name__)` from `app/utils/observability.py`
- **ruff I001 import order**: stdlib → third-party → first-party
- **Never raise `HTTPException` in services** — raise typed `TrueRAGError` subclasses only
- **Never hardcode error codes as strings** — use `ErrorCode` enum from `app/core/errors.py`
- **`extra="ignore"` on document models** — consistent with `TenantDocument.model_config`
- **154 passing tests as baseline** — all must still pass after this story

### Mock Pattern for Agent Tests

The `agents.py` route injects the DB via `request.app.state.motor_client[settings.mongodb_database]`. The mock follows the same `MagicMock` + `__getitem__` chain pattern used in `test_tenants.py`:

```python
FAKE_API_KEY = "test-agent-key"
FAKE_CALLER = {
    "tenant_id": "caller-tenant-id",
    "name": "caller",
    "api_key_hash": hashlib.sha256(FAKE_API_KEY.encode()).hexdigest(),
    "rate_limit_rpm": 60,
    "created_at": datetime.now(UTC),
}

def make_authed_app(find_one_return: dict | None = None) -> FastAPI:
    app = create_app()
    mock_collection = MagicMock()
    # find_one: auth check returns FAKE_CALLER; agent duplicate check returns find_one_return
    def find_one_side_effect(query: dict) -> dict | None:
        if "api_key_hash" in query:
            return FAKE_CALLER
        return find_one_return   # None = no duplicate; dict = duplicate found
    mock_collection.find_one = AsyncMock(side_effect=find_one_side_effect)
    mock_collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake-oid"))
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = MagicMock()
    return app
```

`find_one` is called twice per request: once in `AuthMiddleware` (auth check, query has `api_key_hash`) and once in `create_agent` service (duplicate name check, query has `tenant_id` + `name`). The `side_effect` differentiates these by query structure.

### Valid Request Body Example

```json
{
  "name": "my-rag-agent",
  "chunking_strategy": "fixed_size",
  "vector_store": "pgvector",
  "embedding_provider": "openai",
  "llm_provider": "anthropic",
  "retrieval_mode": "dense",
  "reranker": "none",
  "top_k": 10,
  "semantic_cache_enabled": false
}
```

### Expected 201 Response

```json
{
  "agent_id": "507f1f77bcf86cd799439011",
  "tenant_id": "507f1f77bcf86cd799439012",
  "name": "my-rag-agent",
  "chunking_strategy": "fixed_size",
  "vector_store": "pgvector",
  "embedding_provider": "openai",
  "llm_provider": "anthropic",
  "retrieval_mode": "dense",
  "reranker": "none",
  "top_k": 10,
  "semantic_cache_enabled": false,
  "semantic_cache_threshold": null,
  "status": "active",
  "created_at": "2026-04-25T12:00:00Z",
  "updated_at": "2026-04-25T12:00:00Z"
}
```

### Project Structure Notes

**New files:**
```
app/
├── models/agent.py              ← NEW: AgentDocument, AgentCreateRequest, AgentCreateResponse + VALID_* frozensets
└── services/agent_service.py   ← NEW: create_agent()

tests/
├── api/v1/test_agents.py        ← NEW: endpoint tests
└── services/test_agent_service.py ← NEW: service unit tests
```

**Modified files:**
```
app/
├── api/v1/agents.py             ← MODIFY: replace stub with POST route
├── core/errors.py               ← MODIFY: add AGENT_CONFIG_INVALID, AGENT_ALREADY_EXISTS codes + error classes
└── main.py                      ← MODIFY: add agents collection indexes in lifespan
```

`app/api/v1/__init__.py` already registers `agents.router` — **no change needed**.

### References

- [Source: epics.md#Story 2.3] — User story, all acceptance criteria (FR5, FR21–27)
- [Source: architecture.md#D1] — `agents` collection schema; all field names and types
- [Source: architecture.md#D8] — Namespace format: `{tenant_id}_{agent_id}`
- [Source: architecture.md#D10] — Error envelope: `{error: {code, message, request_id}}`
- [Source: architecture.md#Naming Patterns] — `agent_id` field naming, snake_case, API JSON fields
- [Source: architecture.md#Communication Patterns] — Typed exceptions only, no raw HTTPException in services
- [Source: architecture.md#Structure Patterns] — Test mirrors `app/` structure exactly
- [Source: architecture.md#Provider Registration] — Registry pattern; why validation must NOT use registry
- [Source: app/core/errors.py] — `ForbiddenError`, `TrueRAGError` hierarchy, `ErrorCode` enum
- [Source: app/core/auth.py] — `get_current_tenant` dependency; `SKIP_AUTH_METHOD_PATHS` (POST /v1/tenants excluded but POST /v1/agents is NOT)
- [Source: app/providers/registry.py] — VALID_* frozensets must cover all registry-mapped values; registries empty until Epic 4
- [Source: story 2.2 dev notes] — 154 tests baseline; mock pattern with `find_one_side_effect`; `extra="ignore"` on document models; compound unique index pattern
- [Source: app/main.py] — lifespan index creation pattern; two indexes needed for agents

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

None.

### Completion Notes List

- Implemented full `POST /v1/agents` pipeline: error codes, models, service, route, DB indexes, and tests.
- 15 new tests added (8 API endpoint + 7 service unit); all 169 tests pass with no regressions.
- `VALID_*` frozensets in `app/models/agent.py` are the authoritative config schema — validated in service to return 400 (not 422) per AC2.
- `_FIELD_VALIDATORS` defined at module level (not inside function) for performance; each entry is `(field_name, valid_set)` with value extracted via `getattr`.
- `extra="ignore"` on `AgentDocument` suppresses MongoDB `_id` field during deserialization, consistent with `TenantDocument`.
- Two MongoDB indexes added in `app/main.py` lifespan: compound unique `(tenant_id, name)` for AC3 and unique `(agent_id)` for future Stories 2.4–2.6.
- ruff, mypy --strict, and pytest all pass clean.

### File List

**New Files:**
- `app/models/agent.py`
- `app/services/agent_service.py`
- `tests/api/v1/test_agents.py`
- `tests/services/test_agent_service.py`

**Modified Files:**
- `app/core/errors.py`
- `app/api/v1/agents.py`
- `app/main.py`

## Change Log

- 2026-04-25: Implemented Story 2.3 — RAG Agent Creation with Full Pipeline Configuration. Added `AGENT_CONFIG_INVALID` and `AGENT_ALREADY_EXISTS` error codes, `AgentDocument`/`AgentCreateRequest`/`AgentCreateResponse` models, `create_agent()` service, `POST /v1/agents` route, MongoDB compound index on `(tenant_id, name)` and unique index on `agent_id`. 169 tests pass.
