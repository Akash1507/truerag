# Story 3.3: Ingestion Status Polling & Document Listing

**Status:** done

## Story

**As a** Tenant Developer,
**I want** to poll the ingestion status of a document by job ID and list all documents in my agent,
**So that** I know when a document is queryable and can manage my agent's knowledge base (FR13, FR14).

## Acceptance Criteria

**AC1 — Status poll returns DynamoDB record:**
Given `GET /v1/agents/{agent_id}/documents/{document_id}/status` for an in-progress document
When the request is processed
Then HTTP 200 is returned with `{"document_id": "...", "status": "queued|processing|ready|failed", "error_reason": null|"..."}` read from the DynamoDB `truerag-ingestion-jobs` table

**AC2 — Cross-tenant isolation on status:**
Given polling for a document belonging to a different tenant
When the request is processed
Then HTTP 403 Forbidden is returned; the status is not exposed

**AC3 — Document listing returns paginated MongoDB records:**
Given `GET /v1/agents/{agent_id}/documents` for an agent with multiple documents
When the request is processed
Then a paginated list of document records is returned from MongoDB for that agent only, including `document_id`, `filename`, `file_type`, `status`, `created_at`; cursor-based pagination applies

## Tasks / Subtasks

### [x] Task 1: Add response models to `app/models/document.py`

Add three new Pydantic models after the existing `DocumentUploadResponse`:

```python
class DocumentStatusResponse(BaseModel):
    document_id: str
    status: DocumentStatus
    error_reason: str | None = None

class DocumentListItem(BaseModel):
    document_id: str
    filename: str
    file_type: str
    status: DocumentStatus
    created_at: datetime

class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None = None
```

### [x] Task 2: Add `get_document_status()` to `app/services/ingestion_service.py`

New async function:

```python
async def get_document_status(
    document_id: str,
    agent_id: str,
    tenant_id: str,
    db: AsyncIOMotorDatabase[Any],
    aws_session: aioboto3.Session,
    settings: Settings,
) -> DocumentStatusResponse:
```

**Logic:**
1. Fetch `db["documents"].find_one({"document_id": document_id})` → 404 if None
2. If `doc["tenant_id"] != tenant_id` OR `doc["agent_id"] != agent_id` → raise `ForbiddenError` (403)
3. Use `doc["job_id"]` to call DynamoDB `get_item` for authoritative status:
   ```python
   async with aws_session.client(
       "dynamodb",
       region_name=settings.aws_region,
       endpoint_url=settings.aws_endpoint_url,
   ) as dynamo:
       response = await dynamo.get_item(
           TableName=settings.dynamodb_jobs_table,
           Key={"job_id": {"S": doc["job_id"]}},
           ProjectionExpression="#st, error_reason",
           ExpressionAttributeNames={"#st": "status"},
       )
   ```
4. If `"Item"` not in response → fall back to MongoDB status (job record may not exist if upload failed before DynamoDB write)
5. Extract `status` and `error_reason` from DynamoDB Item; return `DocumentStatusResponse`
6. Structured log: `operation: "get_document_status"`, `tenant_id`, `agent_id`, `document_id`

**Error handling:**
- Document not found in MongoDB → raise `IngestionError("Document not found", http_status=404)` — add `DOCUMENT_NOT_FOUND` error code OR reuse a 404 `IngestionError` with descriptive message (whichever keeps ErrorCode enum minimal; adding `DOCUMENT_NOT_FOUND` is preferred for machine-readability)
- DynamoDB unavailable → let exception propagate (500 via exception handler)

### [x] Task 3: Add `list_documents()` to `app/services/ingestion_service.py`

New async function:

```python
async def list_documents(
    agent_id: str,
    tenant_id: str,
    db: AsyncIOMotorDatabase[Any],
    cursor: str | None,
    limit: int,
) -> tuple[list[DocumentListItem], str | None]:
```

**Logic:**
1. Validate agent ownership first: call `await agent_service.get_agent(agent_id, tenant_id, db)` — raises `AgentNotFoundError` (404) or `ForbiddenError` (403)
2. Build query: `{"agent_id": agent_id, "tenant_id": tenant_id}`
3. If `cursor` provided: `oid = decode_cursor(cursor)` → `query["_id"] = {"$gt": oid}`
4. Fetch `limit + 1` docs sorted by `_id` ascending (same pattern as `agent_service.list_agents`)
5. Determine `has_more`, trim to `limit`, compute `next_cursor = encode_cursor(raw_docs[-1]["_id"]) if has_more else None`
6. Map raw docs to `DocumentListItem` — only include: `document_id`, `filename`, `file_type`, `status`, `created_at`
7. Log: `operation: "list_documents"`, `tenant_id`, `agent_id`, `count`
8. Return `(items, next_cursor)`

### [x] Task 4: Add two new routes to `app/api/v1/documents.py`

Add imports: `DocumentStatusResponse`, `DocumentListResponse`, `DocumentListItem`, `Query`, `InvalidCursorError` from appropriate modules.
Also import `DEFAULT_PAGE_SIZE` from `app.utils.pagination`.

**Route 1 — Status endpoint:**
```python
@router.get(
    "/{agent_id}/documents/{document_id}/status",
    response_model=DocumentStatusResponse,
)
async def get_document_status_route(
    agent_id: str,
    document_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> DocumentStatusResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    aws_session = request.app.state.aws_session
    return await ingestion_service.get_document_status(
        document_id=document_id,
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        db=db,
        aws_session=aws_session,
        settings=settings,
    )
```

**Route 2 — Document listing endpoint:**
```python
@router.get(
    "/{agent_id}/documents",
    response_model=DocumentListResponse,
)
async def list_documents_route(
    agent_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> DocumentListResponse:
    settings = get_settings()
    db = request.app.state.motor_client[settings.mongodb_database]
    try:
        items, next_cursor = await ingestion_service.list_documents(
            agent_id=agent_id,
            tenant_id=caller.tenant_id,
            db=db,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc
    return DocumentListResponse(items=items, next_cursor=next_cursor)
```

**Route ordering matters:** FastAPI matches routes top to bottom. `/{agent_id}/documents/{document_id}/status` must be registered BEFORE `/{agent_id}/documents` to prevent ambiguity. Add in this order:
1. `POST /{agent_id}/documents` (existing)
2. `GET /{agent_id}/documents/{document_id}/status` (new — specific path first)
3. `GET /{agent_id}/documents` (new — generic list)

### [x] Task 5: Add `DOCUMENT_NOT_FOUND` error code and exception to `app/core/errors.py`

Add to `ErrorCode` enum:
```python
DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
```

Add exception class (place after `UnsupportedFileTypeError`):
```python
class DocumentNotFoundError(TrueRAGError):
    def __init__(
        self,
        message: str = "Document not found",
        code: ErrorCode = ErrorCode.DOCUMENT_NOT_FOUND,
        http_status: int = 404,
    ) -> None:
        super().__init__(code=code, message=message, http_status=http_status)
```

Use `DocumentNotFoundError` in `get_document_status()` instead of an `IngestionError` with `http_status=404`.

### [x] Task 6: Add tests to `tests/api/v1/test_documents.py`

Extend the existing test file. Reuse `FAKE_API_KEY`, `FAKE_CALLER`, `FAKE_AGENT_DOC`, `_make_aws_mock`, and the `_make_app` helper with modifications.

**Extend `_make_aws_mock` to accept `dynamo_get_item_return`:**
```python
def _make_aws_mock(
    ...
    dynamo_get_item_return: dict | None = None,
) -> MagicMock:
    ...
    mock_dynamo.get_item = AsyncMock(return_value=dynamo_get_item_return or {
        "Item": {"status": {"S": "queued"}, "error_reason": {"NULL": True}}
    })
```

**Extend `_make_app` to accept `documents_find_one_return` and `documents_find_return`:**
```python
def _make_app(
    ...
    documents_find_one_return: dict | None = None,
    documents_find_cursor: list | None = None,
) -> FastAPI:
    ...
    mock_documents.find_one = AsyncMock(return_value=documents_find_one_return)
    # For find().sort().limit().to_list() chain:
    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=documents_find_cursor or [])
    mock_documents.find = MagicMock(return_value=mock_cursor)
```

**Tests to add:**

```
test_get_document_status_200_success
  → documents.find_one returns valid doc with matching tenant/agent
  → dynamo.get_item returns Item with status "processing"
  → assert 200, body has document_id, status=="processing", error_reason==null

test_get_document_status_403_wrong_tenant
  → documents.find_one returns doc with different tenant_id
  → assert 403, error code "FORBIDDEN"
  → dynamo.get_item NOT called

test_get_document_status_403_wrong_agent
  → documents.find_one returns doc with matching tenant but different agent_id
  → assert 403, error code "FORBIDDEN"

test_get_document_status_404_not_found
  → documents.find_one returns None
  → assert 404, error code "DOCUMENT_NOT_FOUND"

test_get_document_status_200_dynamo_item_missing_falls_back_to_mongo
  → documents.find_one returns valid doc with status "queued"
  → dynamo.get_item returns {} (no "Item" key)
  → assert 200, status=="queued" (MongoDB fallback)

test_get_document_status_200_failed_with_error_reason
  → dynamo.get_item returns Item with status "failed", error_reason "corrupt file"
  → assert 200, status=="failed", error_reason=="corrupt file"

test_list_documents_200_empty
  → agents.find_one returns FAKE_AGENT_DOC (valid agent)
  → documents.find returns []
  → assert 200, {"items": [], "next_cursor": null}

test_list_documents_200_with_items
  → agents.find_one returns FAKE_AGENT_DOC
  → documents.find returns list of 2 doc dicts
  → assert 200, len(items)==2, items have document_id/filename/file_type/status/created_at

test_list_documents_200_pagination_next_cursor
  → documents.find returns limit+1 docs
  → assert 200, next_cursor is not None

test_list_documents_403_agent_belongs_to_other_tenant
  → agents.find_one returns WRONG_TENANT_AGENT_DOC
  → assert 403, error code "FORBIDDEN"

test_list_documents_404_agent_not_found
  → agents.find_one returns None
  → assert 404, error code "AGENT_NOT_FOUND"

test_list_documents_400_invalid_cursor
  → cursor query param is "invalid!!!" (non-base64)
  → assert 400, error code "INVALID_CURSOR"
```

### [x] Task 7: Verify full test suite passes

```bash
cd /home/akash/workspace/products/true-ecosystem/truerag
uv run pytest tests/ -x -q
```

## Dev Notes

### Route Ordering — Critical FastAPI Gotcha

FastAPI registers routes in definition order. The path `/{agent_id}/documents/{document_id}/status` and `/{agent_id}/documents` share a prefix. Define the more specific route first:
```
POST  /{agent_id}/documents              ← existing upload
GET   /{agent_id}/documents/{document_id}/status  ← new (specific)
GET   /{agent_id}/documents              ← new (generic)
```
If `GET /{agent_id}/documents` is registered first, FastAPI will never reach the status endpoint (a literal `{document_id}/status` would match as document_id="status" with no remaining path). Verify in `/docs` Swagger UI that both GET routes appear.

### DynamoDB `get_item` with Reserved Word `status`

DynamoDB `status` is a reserved keyword. Use `ProjectionExpression` with `ExpressionAttributeNames`:
```python
await dynamo.get_item(
    TableName=settings.dynamodb_jobs_table,
    Key={"job_id": {"S": job_id}},
    ProjectionExpression="#st, error_reason",
    ExpressionAttributeNames={"#st": "status"},
)
```
Response format: `response["Item"]["status"]["S"]` and `response["Item"].get("error_reason", {}).get("S")` or `None` if `"NULL": True`.

This pattern is the DynamoDB reserved-word workaround established in Story 3.1/3.2 — same workaround, now for reads.

### DynamoDB Null Handling

DynamoDB represents `null` as `{"NULL": True}`. When reading `error_reason`:
```python
er_attr = item.get("error_reason", {})
error_reason = er_attr.get("S") if "S" in er_attr else None
```
Never call `.get("S")` directly on a null DynamoDB attribute — it returns `None` but the attribute exists as `{"NULL": True}`.

### Two-Step Status Fetch (MongoDB → DynamoDB)

The status endpoint path is `.../{document_id}/status`. The DynamoDB partition key is `job_id`, not `document_id`. Therefore:
1. Fetch MongoDB record by `document_id` → get `job_id` and verify ownership
2. Fetch DynamoDB by `job_id` for authoritative status

This is by design — DynamoDB is the write-ahead journal for the worker; MongoDB tracks the document catalog. They should be in sync; DynamoDB is authoritative for in-progress status.

### Fallback When DynamoDB Item Missing

If `"Item"` is not in the DynamoDB response (e.g., upload failed before DynamoDB write in compensating transaction path), fall back to MongoDB `status` field. This prevents a 500 for edge cases where the job record was not written.

### Pagination Pattern — Established (Must Follow Exactly)

List documents uses identical pattern to `agent_service.list_agents`:
- Sort by `_id` ascending
- Cursor = base64-encoded ObjectId of last item's `_id`
- Query: `{"_id": {"$gt": decoded_oid}}` when cursor present
- `ValueError` from `decode_cursor` → caught at route layer → raise `InvalidCursorError`

Import: `from app.utils.pagination import DEFAULT_PAGE_SIZE, decode_cursor, encode_cursor`

### MongoDB `find()` Chain Mock Pattern

The `db["documents"].find(query).sort("_id", 1).limit(n).to_list(None)` chain requires a chained mock:
```python
mock_cursor = MagicMock()
mock_cursor.sort = MagicMock(return_value=mock_cursor)
mock_cursor.limit = MagicMock(return_value=mock_cursor)
mock_cursor.to_list = AsyncMock(return_value=[...])
mock_documents.find = MagicMock(return_value=mock_cursor)
```
This is the same Motor async driver pattern. `to_list(None)` is awaited — all other chained methods are sync.

### Import Order (ruff I001)

Maintain alphabetical imports within each group. Standard lib → third party → local. Example local import order for `documents.py`:
```python
from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.core.errors import ForbiddenError, InvalidCursorError
from app.models.document import DocumentListResponse, DocumentStatusResponse, DocumentUploadResponse
from app.models.tenant import TenantDocument
from app.services import ingestion_service
from app.utils.pagination import DEFAULT_PAGE_SIZE
```

### `ForbiddenError` vs `DocumentNotFoundError`

Security principle: do not reveal whether a document exists to a caller from a different tenant. Return 403 (not 404) when `tenant_id` or `agent_id` mismatches — identical to how agent_service handles cross-tenant access.

Only return 404 when `db["documents"].find_one({"document_id": document_id})` returns `None` (document genuinely does not exist for anyone).

### Structured Logging

Every service function must emit structured log with:
```python
logger.info(
    "get_document_status",
    extra={
        "operation": "get_document_status",
        "extra_data": {
            "document_id": document_id,
            "agent_id": agent_id,
            "tenant_id": tenant_id,
        },
    },
)
```
Use `logger.debug` for `list_documents` (non-critical path). Use `logger.info` for `get_document_status`. Never log the `status` value itself as a top-level key — keep in `extra_data`.

### No New Routes in `main.py`

Router already registered in `app/api/v1/__init__.py`:
```python
router.include_router(documents.router, prefix="/agents", tags=["documents"])
```
Do NOT touch `main.py` or `app/api/v1/__init__.py`. New endpoints go in `app/api/v1/documents.py` only.

### Files to Create / Modify

```
MODIFY:
├── app/core/errors.py                    ← ADD: DOCUMENT_NOT_FOUND + DocumentNotFoundError
├── app/models/document.py                ← ADD: DocumentStatusResponse, DocumentListItem, DocumentListResponse
├── app/api/v1/documents.py               ← ADD: 2 new GET routes (status + list)
├── app/services/ingestion_service.py     ← ADD: get_document_status(), list_documents()
└── tests/api/v1/test_documents.py        ← ADD: ~12 new tests for the 2 new endpoints

NO CHANGES to:
- app/main.py
- app/api/v1/__init__.py
- app/workers/ingestion_worker.py
- app/workers/sqs_consumer.py
- app/utils/pagination.py  (already has everything needed)
- app/core/config.py  (dynamodb_jobs_table already exists)
```

### Project Structure Notes

- `app/api/v1/documents.py` = architecture `api/v1/documents.py` — all document CRUD routes
- `app/services/ingestion_service.py` = architecture `services/ingestion_service.py` — upload + status + list
- `tests/api/v1/test_documents.py` mirrors `app/api/v1/documents.py` per test structure convention
- DynamoDB table name: `settings.dynamodb_jobs_table` = `"truerag-ingestion-jobs"` (default)
- `db["documents"]` MongoDB collection: same collection used by ingestion_service upload path

### References

- Story 3.3 AC: [Source: _bmad-output/planning-artifacts/epics.md#Story 3.3]
- DynamoDB reserved word workaround: [Source: _bmad-output/implementation-artifacts/3-2-sqs-consumer-worker-and-ingestion-job-status-tracking.md#DynamoDB status Reserved Word]
- DynamoDB table config: [Source: app/core/config.py — `dynamodb_jobs_table`]
- aioboto3 async context manager pattern: [Source: _bmad-output/implementation-artifacts/3-2-sqs-consumer-worker-and-ingestion-job-status-tracking.md#AWS aioboto3 Pattern]
- Pagination implementation: [Source: app/utils/pagination.py]
- Pagination usage pattern: [Source: app/services/agent_service.py — `list_agents()`]
- Router pattern + auth: [Source: app/api/v1/agents.py + app/api/v1/documents.py]
- Test mock factory pattern: [Source: tests/api/v1/test_documents.py — `_make_app`, `_make_aws_mock`]
- ErrorCode enum: [Source: app/core/errors.py]
- MongoDB documents schema: [Source: app/services/ingestion_service.py — `upload_document()`]
- DocumentRecord model: [Source: app/models/document.py]

## Review Findings

### Patch

- [x] [Review][Patch] `job_id` is `str | None` in DocumentRecord but accessed without None guard in `get_document_status` — passes `None` to DynamoDB Key, causing ClientError [app/services/ingestion_service.py:206]
- [x] [Review][Patch] `item["status"]["S"]` unguarded — if DynamoDB Item present but `status` key absent, raises KeyError 500 [app/services/ingestion_service.py:224]
- [x] [Review][Patch] Fallback test `test_get_document_status_200_dynamo_item_missing_falls_back_to_mongo` does not assert `error_reason is None` [tests/api/v1/test_documents.py:369]

### Defer

- [x] [Review][Defer] 403 vs 404 differential leaks document existence to cross-tenant caller [app/services/ingestion_service.py:200] — deferred, spec-mandated behavior consistent with agent_service pattern
- [x] [Review][Defer] No compound MongoDB index `(tenant_id, agent_id, _id)` for cursor pagination query [app/services/ingestion_service.py:260] — deferred, infrastructure/migration task out of story scope
- [x] [Review][Defer] DynamoDB client opened per-request with no connection reuse [app/services/ingestion_service.py:207] — deferred, established pattern across entire codebase
- [x] [Review][Defer] MongoDB document fields accessed via `doc["key"]` without `.get()` guards [app/services/ingestion_service.py:203,220,269] — deferred, pre-existing invariant throughout codebase
- [x] [Review][Defer] Cursor tamper protection absent — valid ObjectId from another collection accepted as cursor [app/services/ingestion_service.py:257] — deferred, pre-existing design decision (no HMAC)

## Dev Agent Record

### Agent Model Used
claude-sonnet-4-6

### Debug Log References
None — implementation went cleanly per spec with no blockers.

### Completion Notes List
- Added `DocumentStatusResponse`, `DocumentListItem`, `DocumentListResponse` to `app/models/document.py`
- Added `DOCUMENT_NOT_FOUND` to `ErrorCode` enum and `DocumentNotFoundError` class to `app/core/errors.py`
- Added `get_document_status()` to `ingestion_service.py`: MongoDB lookup → ownership check → DynamoDB `get_item` with `#st` alias for reserved word `status` → fallback to MongoDB status if DynamoDB item missing
- Added `list_documents()` to `ingestion_service.py`: agent ownership check via `agent_service.get_agent()` → cursor-paginated MongoDB query following identical pattern to `list_agents`
- Added `get_document_status_route` (GET `/{agent_id}/documents/{document_id}/status`) and `list_documents_route` (GET `/{agent_id}/documents`) to `documents.py`; status route registered BEFORE list route to prevent FastAPI path ambiguity
- Extended `_make_aws_mock` with `dynamo_get_item_return` param and `_make_app` with `documents_find_one_return` + `documents_find_cursor` params; added 12 new tests covering all ACs
- 269/269 tests pass with no regressions

### File List
- app/core/errors.py (modified)
- app/models/document.py (modified)
- app/api/v1/documents.py (modified)
- app/services/ingestion_service.py (modified)
- tests/api/v1/test_documents.py (modified)

### Change Log
- 2026-04-30: Story 3.3 created — ingestion status polling via DynamoDB + document listing via MongoDB with cursor pagination
- 2026-04-30: Story 3.3 implemented — all 7 tasks complete, 12 new tests added, 269/269 pass
