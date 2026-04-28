# Story 3.1: Document Upload — S3 Archive & SQS Enqueue

Status: done

## Story

As a Tenant Developer,
I want to upload a document to my agent's knowledge base and receive a job ID immediately,
so that I can submit documents for processing without waiting for the pipeline to complete (FR11, FR12, FR19, FR57).

## Acceptance Criteria

**AC1:** Given `POST /v1/agents/{agent_id}/documents` with a valid PDF, TXT, MD, or DOCX file (multipart/form-data)
When the request is processed
Then:
- Raw file is archived to S3 at key `{tenant_id}/{agent_id}/{document_id}/{filename}` before any processing begins
- A document record is created in MongoDB `documents` collection with `document_id`, `agent_id`, `tenant_id`, `filename`, `file_type`, `s3_key`, `status: queued`, `created_at`
- A job record is created in DynamoDB `truerag-ingestion-jobs` table with `job_id`, `document_id`, `status: queued`
- An SQS message is enqueued with payload `{job_id, tenant_id, agent_id, document_id, s3_key, file_type, timestamp}`
- HTTP 202 Accepted is returned with `{"job_id": "...", "document_id": "...", "status": "queued"}`

**AC2:** Given a document upload for an agent belonging to a different tenant
When the request is processed
Then HTTP 403 Forbidden is returned; no S3 upload, MongoDB write, or SQS message occurs

**AC3:** Given a document upload with an unsupported file type (e.g. `.xlsx`)
When the request is processed
Then HTTP 400 Bad Request is returned; no S3 upload or SQS message occurs

**AC4:** Given S3 archiving succeeds but SQS enqueue fails
When the request is processed
Then the MongoDB document record status is set to `failed` with an error reason; the DynamoDB job record status is also set to `failed`; HTTP 500 is returned; the S3 object is retained for manual recovery

## Tasks / Subtasks

- [x] Task 1: Add `UnsupportedFileTypeError` to `app/core/errors.py` (AC3)
  - [x] 1.1 Add `UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"` to `ErrorCode` StrEnum (after `INGESTION_ERROR`)
  - [x] 1.2 Add class:
    ```python
    class UnsupportedFileTypeError(TrueRAGError):
        def __init__(
            self,
            message: str = "Unsupported file type",
            code: ErrorCode = ErrorCode.UNSUPPORTED_FILE_TYPE,
            http_status: int = 400,
        ) -> None:
            super().__init__(code=code, message=message, http_status=http_status)
    ```

- [x] Task 2: Create `app/models/document.py` (AC1)
  - [x] 2.1 Create file with these models:
    ```python
    from datetime import datetime
    from enum import StrEnum

    from pydantic import BaseModel


    class DocumentStatus(StrEnum):
        queued = "queued"
        processing = "processing"
        ready = "ready"
        failed = "failed"


    class DocumentRecord(BaseModel):
        document_id: str
        agent_id: str
        tenant_id: str
        filename: str
        file_type: str
        s3_key: str
        status: DocumentStatus
        error_reason: str | None = None
        created_at: datetime


    class DocumentUploadResponse(BaseModel):
        job_id: str
        document_id: str
        status: str = "queued"
    ```

- [x] Task 3: Create `app/services/ingestion_service.py` (AC1–AC4)
  - [x] 3.1 Create the service with `upload_document()`. Full implementation:
    ```python
    import json
    from datetime import UTC, datetime
    from typing import Any

    import aioboto3  # type: ignore[import-untyped]
    from bson import ObjectId
    from fastapi import UploadFile
    from motor.motor_asyncio import AsyncIOMotorDatabase

    from app.core.config import Settings
    from app.core.errors import IngestionError, UnsupportedFileTypeError
    from app.models.document import DocumentUploadResponse
    from app.services import agent_service
    from app.utils.observability import get_logger

    logger = get_logger(__name__)

    SUPPORTED_FILE_TYPES: frozenset[str] = frozenset({"pdf", "txt", "md", "docx"})


    async def upload_document(
        file: UploadFile,
        agent_id: str,
        tenant_id: str,
        db: AsyncIOMotorDatabase[Any],
        aws_session: aioboto3.Session,
        settings: Settings,
    ) -> DocumentUploadResponse:
        # Validate agent ownership — raises AgentNotFoundError (404) or ForbiddenError (403)
        await agent_service.get_agent(agent_id, tenant_id, db)

        # Validate file type from extension
        filename: str = file.filename or ""
        file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if file_ext not in SUPPORTED_FILE_TYPES:
            raise UnsupportedFileTypeError(
                f"Unsupported file type: {file_ext!r}. Supported: {sorted(SUPPORTED_FILE_TYPES)}"
            )

        document_id = str(ObjectId())
        job_id = str(ObjectId())
        now = datetime.now(UTC)
        s3_key = f"{tenant_id}/{agent_id}/{document_id}/{filename}"

        content = await file.read()

        # 1. Archive to S3 — failure propagates as 500 before any writes
        async with aws_session.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as s3:
            await s3.put_object(
                Bucket=settings.s3_document_bucket,
                Key=s3_key,
                Body=content,
            )

        # 2. Insert MongoDB document record
        await db["documents"].insert_one(
            {
                "document_id": document_id,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "filename": filename,
                "file_type": file_ext,
                "s3_key": s3_key,
                "status": "queued",
                "error_reason": None,
                "created_at": now,
            }
        )

        # 3. Insert DynamoDB job record
        async with aws_session.client(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as dynamo:
            await dynamo.put_item(
                TableName=settings.dynamodb_jobs_table,
                Item={
                    "job_id": {"S": job_id},
                    "document_id": {"S": document_id},
                    "status": {"S": "queued"},
                },
            )

        # 4. Enqueue SQS message — failure rolls status to failed on both stores
        try:
            async with aws_session.client(
                "sqs",
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            ) as sqs:
                await sqs.send_message(
                    QueueUrl=settings.sqs_ingestion_queue_url,
                    MessageBody=json.dumps(
                        {
                            "job_id": job_id,
                            "tenant_id": tenant_id,
                            "agent_id": agent_id,
                            "document_id": document_id,
                            "s3_key": s3_key,
                            "file_type": file_ext,
                            "timestamp": now.isoformat(),
                        }
                    ),
                )
        except Exception as sqs_exc:
            error_reason = str(sqs_exc)
            await db["documents"].update_one(
                {"document_id": document_id},
                {"$set": {"status": "failed", "error_reason": error_reason}},
            )
            async with aws_session.client(
                "dynamodb",
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            ) as dynamo:
                await dynamo.update_item(
                    TableName=settings.dynamodb_jobs_table,
                    Key={"job_id": {"S": job_id}},
                    UpdateExpression="SET #st = :st, error_reason = :er",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={
                        ":st": {"S": "failed"},
                        ":er": {"S": error_reason},
                    },
                )
            logger.error(
                "sqs_enqueue_failed",
                extra={
                    "operation": "upload_document",
                    "extra_data": {
                        "document_id": document_id,
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "error": error_reason,
                    },
                },
            )
            raise IngestionError(f"SQS enqueue failed: {sqs_exc}") from sqs_exc

        logger.info(
            "document_uploaded",
            extra={
                "operation": "upload_document",
                "extra_data": {
                    "document_id": document_id,
                    "job_id": job_id,
                    "agent_id": agent_id,
                    "tenant_id": tenant_id,
                    "file_type": file_ext,
                },
            },
        )

        return DocumentUploadResponse(
            job_id=job_id, document_id=document_id, status="queued"
        )
    ```

- [x] Task 4: Implement `app/api/v1/documents.py` route (AC1–AC4)
  - [x] 4.1 Replace the stub with:
    ```python
    from fastapi import APIRouter, Depends, Request, UploadFile, status

    from app.core.auth import get_current_tenant
    from app.core.config import get_settings
    from app.models.agent import TenantDocument
    from app.models.document import DocumentUploadResponse
    from app.services import ingestion_service

    router = APIRouter()


    @router.post(
        "/{agent_id}/documents",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=DocumentUploadResponse,
    )
    async def upload_document_route(
        agent_id: str,
        file: UploadFile,
        request: Request,
        caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
    ) -> DocumentUploadResponse:
        settings = get_settings()
        db = request.app.state.motor_client[settings.mongodb_database]
        aws_session = request.app.state.aws_session
        return await ingestion_service.upload_document(
            file=file,
            agent_id=agent_id,
            tenant_id=caller.tenant_id,
            db=db,
            aws_session=aws_session,
            settings=settings,
        )
    ```

- [x] Task 5: Fix router prefix in `app/api/v1/__init__.py` (AC1)
  - [x] 5.1 Change `prefix="/documents"` to `prefix="/agents"` for the documents router:
    ```python
    router.include_router(documents.router, prefix="/agents", tags=["documents"])
    ```
    This gives the correct path `/v1/agents/{agent_id}/documents`.
    Both `agents.router` and `documents.router` at prefix `/agents` — valid FastAPI pattern, no path collision.

- [x] Task 6: Write tests (AC1–AC4)
  - [x] 6.1 Create `tests/api/v1/test_documents.py`

    Fixture pattern — extend the `make_authed_app` style from `test_agents.py` to add AWS mock:
    ```python
    def _make_aws_mock(
        s3_put_side_effect: Exception | None = None,
        sqs_send_side_effect: Exception | None = None,
        dynamo_put_side_effect: Exception | None = None,
    ) -> MagicMock:
        """Returns a mock aioboto3.Session whose .client() context manager yields service mocks."""

        def make_cm(mock_client: AsyncMock) -> MagicMock:
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=mock_client)
            cm.__aexit__ = AsyncMock(return_value=None)
            return cm

        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(side_effect=s3_put_side_effect)

        mock_sqs = AsyncMock()
        mock_sqs.send_message = AsyncMock(side_effect=sqs_send_side_effect)

        mock_dynamo = AsyncMock()
        mock_dynamo.put_item = AsyncMock(side_effect=dynamo_put_side_effect)
        mock_dynamo.update_item = AsyncMock(return_value={})

        def client_factory(service: str, **kwargs: Any) -> MagicMock:
            if service == "s3":
                return make_cm(mock_s3)
            if service == "sqs":
                return make_cm(mock_sqs)
            return make_cm(mock_dynamo)

        mock_session = MagicMock()
        mock_session.client = MagicMock(side_effect=client_factory)
        return mock_session
    ```

    **Tests to implement:**

    - `test_upload_document_202_success` — valid PDF upload, all AWS mocks succeed, agent `find_one` returns `FAKE_AGENT_DOC`; assert 202, response has `job_id`, `document_id`, `status="queued"`
    - `test_upload_document_403_wrong_tenant` — agent `find_one` returns doc with different `tenant_id` → 403, `FORBIDDEN`; assert `insert_one` on documents NOT called
    - `test_upload_document_404_agent_not_found` — agent `find_one` returns `None` → 404, `AGENT_NOT_FOUND`
    - `test_upload_document_400_unsupported_type` — upload `.xlsx` file → 400, `UNSUPPORTED_FILE_TYPE`; assert `put_object` NOT called
    - `test_upload_document_500_sqs_failure` — S3 + Mongo + DynamoDB succeed, SQS raises `RuntimeError("queue error")`; assert 500, `INGESTION_ERROR`; assert `update_one` called on documents with `status=failed`; assert `update_item` called on DynamoDB
    - `test_upload_document_401_no_api_key` — no `X-API-Key` header → 401

    Pattern for multipart upload in tests:
    ```python
    response = await client.post(
        f"/v1/agents/{FAKE_AGENT_DOC['agent_id']}/documents",
        files={"file": ("report.pdf", b"PDF content", "application/pdf")},
        headers={"X-API-Key": FAKE_API_KEY},
    )
    ```

  - [x] 6.2 Create `tests/services/test_ingestion_service.py`

    Tests call `upload_document()` directly with mocked `db`, `aws_session`, `settings`.

    Mock `agent_service.get_agent` via `patch("app.services.ingestion_service.agent_service.get_agent")`.

    **Tests to implement:**

    - `test_upload_document_success` — patches `agent_service.get_agent` to return `FAKE_AGENT_DOC`; all AWS mocks succeed; assert `insert_one` called with correct fields (`status="queued"`, correct `s3_key` format)
    - `test_upload_document_s3_key_format` — assert s3_key is exactly `f"{tenant_id}/{agent_id}/{document_id}/{filename}"`; extract `document_id` from the `insert_one` call args
    - `test_upload_document_sqs_message_format` — capture `send_message` call; parse `MessageBody` JSON; assert all 7 fields present (`job_id`, `tenant_id`, `agent_id`, `document_id`, `s3_key`, `file_type`, `timestamp`)
    - `test_upload_document_unsupported_type_xlsx` — file with `.xlsx` extension → raises `UnsupportedFileTypeError`; `put_object` NOT called
    - `test_upload_document_unsupported_type_no_extension` — file with no extension → raises `UnsupportedFileTypeError`
    - `test_upload_document_sqs_failure_marks_both_failed` — S3 + Mongo + Dynamo succeed, `sqs.send_message` raises; assert `update_one` called with `{"$set": {"status": "failed", "error_reason": ...}}`; assert `dynamo.update_item` called; raises `IngestionError`
    - `test_upload_document_returns_correct_response` — assert `DocumentUploadResponse` has `status="queued"`, non-empty `job_id`, non-empty `document_id`

  - [x] 6.3 Run `ruff check app/ tests/` — must exit 0
  - [x] 6.4 Run `mypy app/ --strict` — must exit 0
  - [x] 6.5 Run `pytest tests/ -v` — all tests pass (223 existing + ~13 new); no regressions

## Dev Notes

### Router Prefix: The `__init__.py` `prefix="/documents"` Must Become `prefix="/agents"`

The scaffolded `app/api/v1/__init__.py` registers `documents.router` at prefix `/documents` — this gives `/v1/documents/...` which is wrong. The story requires `POST /v1/agents/{agent_id}/documents`.

Fix: Change to `prefix="/agents"`. FastAPI handles two routers at the same prefix without conflict — `agents.router` and `documents.router` both at `/agents` is valid because their path templates don't overlap.

### `app/models/document.py` Does Not Exist Yet

This is a new file. The architecture spec at `architecture.md#D1` and `#Project Structure` shows:
```
app/models/document.py  # Document record + ingestion job status schema
```
It is referenced in Story 2.6 dev notes ("collection created in Epic 3") but the file was intentionally deferred.

### AWS Client Pattern: `aioboto3` Async Context Managers

All AWS clients use async context managers. `aws_session` comes from `request.app.state.aws_session` (set in `app/main.py:lifespan` as `application.state.aws_session = aioboto3.Session()`).

```python
async with aws_session.client("s3", region_name=..., endpoint_url=...) as s3:
    await s3.put_object(...)
```

`endpoint_url=settings.aws_endpoint_url` supports LocalStack for local dev — it is `None` in production so boto3 uses the real AWS endpoint.

Always pass both `region_name=settings.aws_region` and `endpoint_url=settings.aws_endpoint_url` to every AWS client.

### DynamoDB Attribute Name `status` Is Reserved

`status` is a DynamoDB reserved word. The `update_item` for SQS failure MUST use `ExpressionAttributeNames`:
```python
UpdateExpression="SET #st = :st, error_reason = :er",
ExpressionAttributeNames={"#st": "status"},
```
NOT `"SET status = :st"` — that raises a `ParamValidationError` at runtime.

### SQS Failure: S3 Object Is Retained (Not Deleted)

Per AC4, when SQS enqueue fails the S3 object is **retained** for manual recovery. Do NOT attempt to delete the S3 object in the error handler. Only MongoDB and DynamoDB records are updated to `failed`.

### Operation Order: S3 → MongoDB → DynamoDB → SQS

This order is intentional:
1. S3 upload first — if it fails, no DB writes occur (clean failure)
2. MongoDB insert — if it fails, S3 has the file but no record (acceptable; S3 is durable)
3. DynamoDB insert — job record created
4. SQS last — only SQS failure triggers the status rollback

### MongoDB `documents` Collection: No Index Required for Story 3.1

The `documents` collection index on `agent_id` is not required for the upload story. Query/listing needs it but that's Story 3.3. Do NOT add index setup to `app/main.py` lifespan in this story.

### `agent_service.get_agent()` Handles Both 404 and 403

Calling `await agent_service.get_agent(agent_id, tenant_id, db)` at the top of `upload_document()` handles both:
- `AgentNotFoundError` (404) when agent does not exist
- `ForbiddenError` (403) when agent belongs to different tenant

Do NOT re-implement ownership checks inline — reuse the existing service method.

### `file.filename` May Be `None`

`UploadFile.filename` is `str | None`. Guard:
```python
filename: str = file.filename or ""
file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
```
An empty extension is not in `SUPPORTED_FILE_TYPES`, so `UnsupportedFileTypeError` is raised automatically.

### `TenantDocument` import in `documents.py`

`get_current_tenant` returns a `TenantDocument`. Import from `app.models.agent`:
```python
from app.models.agent import TenantDocument
```
This is the same pattern used in `app/api/v1/agents.py`.

### Import Order (ruff I001)

In `ingestion_service.py`, third-party imports before first-party:
```
stdlib: datetime, json, typing
third-party: aioboto3, bson, fastapi, motor
first-party: app.*
```

In `documents.py`:
```
stdlib: (none)
third-party: fastapi
first-party: app.*
```

### Previously Established Patterns (Must Follow)

- `from datetime import UTC` then `datetime.now(UTC)` — NEVER `datetime.utcnow()`
- Built-in generics: `list[X]`, `dict[K, V]` — NOT `List`, `Dict`
- `X | None` — NOT `Optional[X]`
- Never `print()` or `import logging` — always `get_logger(__name__)` from `app/utils/observability.py`
- Never raise `HTTPException` in services — raise typed `TrueRAGError` subclasses only
- Never hardcode error codes as strings — use `ErrorCode` enum
- `from enum import StrEnum` for enum classes
- 223 passing tests as baseline — all must still pass after this story

### Files to Create / Modify

```
MODIFY:
├── app/core/errors.py                   ← ADD: UNSUPPORTED_FILE_TYPE + UnsupportedFileTypeError
├── app/api/v1/__init__.py               ← CHANGE: prefix="/documents" → prefix="/agents"
└── app/api/v1/documents.py              ← REPLACE stub with upload route

CREATE:
├── app/models/document.py               ← DocumentStatus, DocumentRecord, DocumentUploadResponse
├── app/services/ingestion_service.py    ← upload_document()
├── tests/api/v1/test_documents.py       ← ~6 API tests
└── tests/services/test_ingestion_service.py  ← ~7 service tests
```

### Project Structure Notes

- Architecture spec `project-structure#app/api/v1/documents.py` confirms this file handles FR11-17, FR57
- Architecture spec `project-structure#app/services/ingestion_service.py` confirms this service handles "Document upload orchestration, S3 archive, SQS enqueue"
- Architecture spec `project-structure#app/models/document.py` confirms "Document record + ingestion job status schema"
- No changes to `app/main.py`, `app/core/auth.py`, `app/core/dependencies.py`, `app/models/agent.py`

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.1] — User story and all acceptance criteria
- [Source: _bmad-output/planning-artifacts/architecture.md#D1] — MongoDB collections: `documents` field list
- [Source: _bmad-output/planning-artifacts/architecture.md#D2] — DynamoDB `truerag-ingestion-jobs` table: partition key `job_id`
- [Source: _bmad-output/planning-artifacts/architecture.md#D9] — SQS queue config + message format (7 fields)
- [Source: _bmad-output/planning-artifacts/architecture.md#D12] — ECS topology: `truerag-api` (this story) vs `truerag-worker` (Story 3.2)
- [Source: _bmad-output/planning-artifacts/architecture.md#Project Structure] — Confirms `documents.py`, `ingestion_service.py`, `document.py` paths
- [Source: app/core/config.py] — `sqs_ingestion_queue_url`, `s3_document_bucket`, `dynamodb_jobs_table`, `aws_endpoint_url`, `aws_region`
- [Source: app/core/errors.py] — Existing error class pattern to follow for `UnsupportedFileTypeError`
- [Source: app/main.py:85] — `application.state.aws_session = aioboto3.Session()` — how aws_session is stored
- [Source: app/services/agent_service.py:102-112] — `get_agent()` implementation for 404/403 checks
- [Source: tests/api/v1/test_agents.py:53-100] — `make_authed_app` pattern: how to mock MongoDB + app.state for tests
- [Source: _bmad-output/implementation-artifacts/2-6-agent-deletion.md#Dev Notes] — Established patterns (datetime, generics, error raising, ruff I001 order)

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Dev note says `TenantDocument` imports from `app.models.agent` but actual codebase (and `agents.py`) imports from `app.models.tenant`. Fixed import accordingly.
- `python-multipart` was not in the virtual environment; installed it to support `UploadFile` in FastAPI route registration.

### Completion Notes List

- Task 1: Added `UNSUPPORTED_FILE_TYPE` to `ErrorCode` and `UnsupportedFileTypeError` class to `app/core/errors.py`.
- Task 2: Created `app/models/document.py` with `DocumentStatus`, `DocumentRecord`, `DocumentUploadResponse`.
- Task 3: Created `app/services/ingestion_service.py` with `upload_document()` — S3→MongoDB→DynamoDB→SQS order, SQS failure marks both stores as `failed` and raises `IngestionError`.
- Task 4: Replaced `documents.py` stub with full upload route at `POST /{agent_id}/documents`, status 202.
- Task 5: Fixed `app/api/v1/__init__.py` documents router prefix from `/documents` → `/agents` for correct path `/v1/agents/{agent_id}/documents`.
- Task 6: 6 API tests + 7 service tests. All 236 tests pass (223 baseline + 13 new). ruff clean. mypy strict clean.

### File List

- app/core/errors.py (modified)
- app/models/document.py (created)
- app/services/ingestion_service.py (created)
- app/api/v1/documents.py (modified)
- app/api/v1/__init__.py (modified)
- tests/api/v1/test_documents.py (created)
- tests/services/test_ingestion_service.py (created)

### Change Log

- 2026-04-27: Implemented Story 3.1 — document upload endpoint with S3 archive, MongoDB record, DynamoDB job, SQS enqueue. Added `UnsupportedFileTypeError`. Fixed documents router prefix. 13 new tests added.
