# Story 3.2: SQS Consumer Worker & Ingestion Job Status Tracking

## Story

**As a** Tenant Developer,
**I want** the SQS worker to process enqueued documents and update job status at each stage,
**So that** the ingestion pipeline runs asynchronously without blocking the API, and I can observe what stage my document is at (FR12, NFR14, NFR16).

**Status:** done

---

## Acceptance Criteria

**AC1 — Processing start:**
Given an SQS message is dequeued by the `truerag-worker` ECS task
When processing begins
Then both the MongoDB `documents` record and the DynamoDB `truerag-ingestion-jobs` record are updated to `status: processing`; the SQS message is NOT deleted until processing fully completes.

**AC2 — Transient failure:**
Given a transient failure during processing (e.g. S3 read timeout, embedding API timeout)
When the worker encounters the error
Then the SQS message becomes visible again after the visibility timeout (300s); up to 3 delivery attempts are made; on the 3rd failure the message is moved to the DLQ and both the MongoDB document record and the DynamoDB job record are updated to `status: failed` with the error reason.

**AC3 — Permanent failure:**
Given a permanent failure (e.g. corrupt file, unsupported content)
When the worker detects it
Then both the MongoDB document record and the DynamoDB job record are immediately updated to `status: failed` with a descriptive error reason; the SQS message is deleted (not retried); no partial chunks are stored.

**AC4 — Success:**
Given the worker processes a document successfully
When processing completes
Then both the MongoDB document record and the DynamoDB job record are updated to `status: ready`; the SQS message is deleted.

---

## Tasks / Subtasks

### Task 1: Add `PermanentIngestionError` to `app/core/errors.py`
- [x] Add `PERMANENT_INGESTION_ERROR = "PERMANENT_INGESTION_ERROR"` to `ErrorCode` enum
- [x] Add `PermanentIngestionError(TrueRAGError)` class following the exact pattern of `IngestionError`
- [x] Default message: `"Permanent ingestion failure — document cannot be retried"`
- [x] `http_status=500` (worker-only — never surfaced via HTTP, but keeps interface consistent)

### Task 2: Create `app/workers/__init__.py`
- [x] Empty file — marks `workers/` as a Python package
- [x] No imports

### Task 3: Create `app/workers/ingestion_worker.py` — job processor with status tracking
- [x] Define `IngestionJobPayload` (dataclass or TypedDict) with fields: `job_id`, `tenant_id`, `agent_id`, `document_id`, `s3_key`, `file_type`, `timestamp` — mirrors exact SQS message format from D9
- [x] Implement `async def process_job(payload: IngestionJobPayload, db: AsyncIOMotorDatabase, aws_session: aioboto3.Session, settings: Settings) -> None`
- [x] Step 1: Update both MongoDB and DynamoDB to `status: processing` (see critical patterns below)
- [x] Step 2: Call `await _run_pipeline_stub(payload, aws_session, settings)` — pipeline placeholder (logs "pipeline not yet implemented for Epic 4" and returns; see stub note)
- [x] Step 3: Update both MongoDB and DynamoDB to `status: ready`, `error_reason: None`
- [x] On `PermanentIngestionError` raised inside stub: re-raise as-is (consumer handles delete + status update)
- [x] On any other exception (transient): re-raise as-is (consumer handles DLQ logic)
- [x] `_run_pipeline_stub()` is a private async function that logs and returns — it does NOT raise unless testing permanent failure path; the stub is the hook for Epic 4 to replace

### Task 4: Create `app/workers/sqs_consumer.py` — long-poll loop and DLQ handling
- [x] Define `MAX_RECEIVE_COUNT: int = 3` module-level constant (matches D9 `max receive count: 3`)
- [x] Implement `async def run_consumer(aws_session: aioboto3.Session, db: AsyncIOMotorDatabase, settings: Settings) -> None` — the main loop
- [x] Long-poll: `receive_message(QueueUrl=..., MaxNumberOfMessages=1, WaitTimeSeconds=20, AttributeNames=["ApproximateReceiveCount"])`
- [x] For each message: call `await _dispatch(msg, aws_session, db, settings)`
- [x] `_dispatch` flow:
  1. Parse `msg["Body"]` as JSON → build `IngestionJobPayload`
  2. Extract `receive_count = int(msg["Attributes"]["ApproximateReceiveCount"])`
  3. Call `await process_job(payload, db, aws_session, settings)`
  4. On success: delete message via `sqs.delete_message(QueueUrl=..., ReceiptHandle=msg["ReceiptHandle"])`
  5. On `PermanentIngestionError`:
     - Update both MongoDB + DynamoDB to `status: failed, error_reason: str(exc)`
     - DELETE message (permanent — must not retry or DLQ)
     - Log at ERROR level
  6. On any other exception (transient):
     - If `receive_count >= MAX_RECEIVE_COUNT`: update both stores to `status: failed, error_reason: str(exc)` — do NOT delete (SQS moves to DLQ automatically after visibility timeout)
     - If `receive_count < MAX_RECEIVE_COUNT`: do NOT delete, do NOT update status — visibility timeout expires and SQS re-delivers
     - Log at ERROR level with receive_count
- [x] Implement `async def _update_status(job_id: str, document_id: str, status: str, error_reason: str | None, db: AsyncIOMotorDatabase, aws_session: aioboto3.Session, settings: Settings) -> None` — shared helper for all status updates (avoids duplication across dispatch and process_job)
- [x] Entry point `if __name__ == "__main__":` block using `asyncio.run()` with motor + aioboto3 setup

### Task 5: Create `tests/workers/__init__.py`
- [x] Empty file

### Task 6: Create `tests/workers/test_ingestion_worker.py`
- [x] `_make_aws_mock()` factory following exact pattern from `tests/services/test_ingestion_service.py` (context manager mocks for SQS + DynamoDB)
- [x] `_make_db()` factory following exact pattern from `tests/services/test_ingestion_service.py`
- [x] Test: `test_process_job_updates_status_to_processing` — verify both MongoDB `update_one` and DynamoDB `update_item` called with `status=processing` before pipeline stub
- [x] Test: `test_process_job_success_updates_status_to_ready` — verify both stores updated to `status=ready` on success; no `error_reason`
- [x] Test: `test_process_job_permanent_failure_reraises` — mock stub to raise `PermanentIngestionError`; verify exception propagates (consumer will handle status update)
- [x] Test: `test_process_job_transient_failure_reraises` — mock stub to raise `RuntimeError`; verify exception propagates

### Task 7: Create `tests/workers/test_sqs_consumer.py`
- [x] `_make_sqs_message(receive_count: int, body: dict) -> dict` factory helper
- [x] Test: `test_dispatch_success_deletes_message` — mock `process_job` to return; verify `sqs.delete_message` called with correct `ReceiptHandle`
- [x] Test: `test_dispatch_transient_first_attempt_does_not_delete` — mock `process_job` to raise `RuntimeError`; `receive_count=1`; verify `sqs.delete_message` NOT called; status NOT updated to failed
- [x] Test: `test_dispatch_transient_third_attempt_updates_failed_does_not_delete` — mock `process_job` to raise `RuntimeError("timeout")`; `receive_count=3`; verify both stores updated to `status=failed, error_reason="timeout"`; verify `sqs.delete_message` NOT called
- [x] Test: `test_dispatch_permanent_failure_updates_failed_and_deletes` — mock `process_job` to raise `PermanentIngestionError("corrupt")`; verify both stores updated to `status=failed`; verify `sqs.delete_message` called
- [x] Test: `test_dispatch_parses_sqs_message_body_correctly` — verify JSON body parsed into `IngestionJobPayload` with all 7 fields

### Task 8: Verify full test suite passes
- [x] Run `uv run pytest` — all tests pass (236 baseline + 9 new worker tests = 245 total)
- [x] Run `uv run ruff check .` — no linting errors (enforce import order I001)
- [x] Run `uv run mypy app/ tests/ --strict` — no type errors

---

## Dev Notes

### Scope Boundary: Pipeline Stub

`_run_pipeline_stub()` in `ingestion_worker.py` is intentionally empty for story 3.2. It logs and returns. Epic 4 (stories 4.1–4.3) replaces it with real parse→chunk→embed→upsert logic. **Do not implement any document parsing, chunking, or embedding in this story.** The worker infrastructure must be complete and all status transitions must be testable with the stub.

### DLQ Detection: `ApproximateReceiveCount`

SQS moves a message to the DLQ automatically when receive count exceeds `maxReceiveCount` (3). However, the worker must check `ApproximateReceiveCount` on its own to update status to `failed` BEFORE the message enters DLQ (since the consumer won't see it again after DLQ transfer).

```python
receive_count = int(msg["Attributes"]["ApproximateReceiveCount"])
# receive_count == 3 means this is the 3rd (final) delivery attempt
# After this attempt fails, SQS moves the message to DLQ on visibility timeout expiry
```

**CRITICAL**: Request `AttributeNames=["ApproximateReceiveCount"]` in `receive_message`. Without this, `msg["Attributes"]` is empty and the key will raise `KeyError`.

### DynamoDB `status` Reserved Word

`status` is a DynamoDB reserved word. Always use `ExpressionAttributeNames={"#st": "status"}` in `UpdateExpression`. Established in story 3.1 — do not deviate.

**Update to `processing` (no error_reason change needed):**
```python
UpdateExpression="SET #st = :st",
ExpressionAttributeNames={"#st": "status"},
ExpressionAttributeValues={":st": {"S": "processing"}},
```

**Update to `failed`:**
```python
UpdateExpression="SET #st = :st, error_reason = :er",
ExpressionAttributeNames={"#st": "status"},
ExpressionAttributeValues={":st": {"S": "failed"}, ":er": {"S": error_reason}},
```

**Update to `ready`:**
```python
UpdateExpression="SET #st = :st",
ExpressionAttributeNames={"#st": "status"},
ExpressionAttributeValues={":st": {"S": "ready"}},
```

### AWS aioboto3 Pattern (Established in 3.1)

All AWS clients use async context managers. Same pattern as `ingestion_service.py`:
```python
async with aws_session.client(
    "sqs",
    region_name=settings.aws_region,
    endpoint_url=settings.aws_endpoint_url,
) as sqs:
    response = await sqs.receive_message(...)
```

`aws_session` is `aioboto3.Session()`. For the standalone worker entry point, create it with `aioboto3.Session()` directly (no FastAPI app state).

### MongoDB Update Pattern (Established)

```python
await db["documents"].update_one(
    {"document_id": document_id},
    {"$set": {"status": "processing"}},
)
```

For `failed`: also set `error_reason`:
```python
{"$set": {"status": "failed", "error_reason": error_reason}}
```

### Worker Entry Point: Standalone Process

`sqs_consumer.py` runs as `python -m app.workers.sqs_consumer` inside `truerag-worker` ECS task. It has NO FastAPI app, NO HTTP listener. The entry point must:
1. Load `Settings()` from `app.core.config`
2. Create `aioboto3.Session()`
3. Create motor client from `settings.mongodb_uri` → get DB `settings.mongodb_db_name`
4. Call `asyncio.run(run_consumer(aws_session, db, settings))`

Check `app/core/config.py` for the exact field names for `mongodb_uri` and `mongodb_db_name` — do NOT guess or hardcode.

### `PermanentIngestionError` vs `IngestionError`

- `IngestionError` (existing) — used by the API-side upload when SQS enqueue fails; represents transient/unexpected failures in API path
- `PermanentIngestionError` (new) — used exclusively by worker; signals the document cannot be retried; causes message deletion instead of DLQ

Consumer code:
```python
try:
    await process_job(...)
    # success → delete message
except PermanentIngestionError as exc:
    # update failed + delete message
except Exception as exc:
    # check receive_count for DLQ detection
    # do NOT delete message
```

### Import Order (ruff I001)

ruff enforces alphabetical import groups. Worker imports should follow established pattern:
```python
# stdlib
import asyncio
import json
# third-party
import aioboto3
from motor.motor_asyncio import AsyncIOMotorDatabase
# local
from app.core.config import Settings
from app.core.errors import IngestionError, PermanentIngestionError
from app.utils.observability import get_logger
```

### Test Mock Pattern (Established — Must Follow Exactly)

From `tests/services/test_ingestion_service.py`:
```python
def _make_aws_mock(sqs_receive_return: dict | None = None) -> MagicMock:
    def make_cm(mock_client: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_sqs = AsyncMock()
    mock_sqs.receive_message = AsyncMock(return_value=sqs_receive_return or {"Messages": []})
    mock_sqs.delete_message = AsyncMock(return_value={})

    mock_dynamo = AsyncMock()
    mock_dynamo.update_item = AsyncMock(return_value={})

    def client_factory(service: str, **kwargs: Any) -> MagicMock:
        if service == "sqs":
            return make_cm(mock_sqs)
        return make_cm(mock_dynamo)

    mock_session = MagicMock()
    mock_session.client = MagicMock(side_effect=client_factory)
    return mock_session
```

The consumer tests patch `process_job` via `unittest.mock.patch` to isolate consumer dispatch logic from worker logic.

### Structured Logging (D15)

All worker log entries follow the established `get_logger(__name__)` + `extra={"operation": ..., "extra_data": {...}}` pattern from `ingestion_service.py`. Key log operations:
- `"job_dispatch_started"` — with `job_id`, `tenant_id`, `document_id`, `receive_count`
- `"job_completed"` — with `job_id`, `document_id`
- `"job_transient_failure"` — with `job_id`, `receive_count`, `error`
- `"job_permanent_failure"` — with `job_id`, `error`
- `"job_dlq_threshold_reached"` — with `job_id`, `receive_count`

### Files to Create / Modify

```
MODIFY:
└── app/core/errors.py                         ← ADD: PERMANENT_INGESTION_ERROR + PermanentIngestionError

CREATE:
├── app/workers/__init__.py                    ← empty package init
├── app/workers/ingestion_worker.py            ← IngestionJobPayload + process_job() + _run_pipeline_stub()
├── app/workers/sqs_consumer.py                ← run_consumer() + _dispatch() + _update_status() + __main__
├── tests/workers/__init__.py                  ← empty
├── tests/workers/test_ingestion_worker.py     ← ~4 tests
└── tests/workers/test_sqs_consumer.py         ← ~5 tests

NO CHANGES to:
- app/main.py (worker is standalone, not part of FastAPI app)
- app/api/v1/documents.py
- app/models/document.py
- app/services/ingestion_service.py
- app/core/config.py (all required settings already exist)
```

### Project Structure Notes

- `app/workers/` maps to architecture spec `#Project Structure: workers/` — SQS consumer worker, ingestion path
- `app/workers/sqs_consumer.py` = architecture `workers/sqs_consumer.py` — long-poll loop, DLQ handling
- `app/workers/ingestion_worker.py` = architecture `workers/ingestion_worker.py` — job processor
- `tests/workers/` mirrors `app/workers/` per project test structure convention
- `app/pipelines/ingestion/pipeline.py` (architecture ref) is the Epic 4 target — do NOT create it in story 3.2

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.2] — User story and all acceptance criteria
- [Source: _bmad-output/planning-artifacts/architecture.md#D9] — SQS queue config: standard queue, visibility timeout 300s, max receive count 3, DLQ retention 14 days, message format (7 fields)
- [Source: _bmad-output/planning-artifacts/architecture.md#D12] — ECS topology: `truerag-worker` SQS consumer, no HTTP listener; `truerag-api` no SQS consumer
- [Source: _bmad-output/planning-artifacts/architecture.md#D2] — DynamoDB `truerag-ingestion-jobs` partition key: `job_id`
- [Source: _bmad-output/planning-artifacts/architecture.md#D15] — Structured logging format: timestamp, level, tenant_id, request_id, operation, latency_ms, extra
- [Source: _bmad-output/planning-artifacts/architecture.md#Project Structure] — `app/workers/sqs_consumer.py` and `app/workers/ingestion_worker.py` paths
- [Source: app/core/errors.py] — `IngestionError` pattern; `ErrorCode` enum; `TrueRAGError` base class
- [Source: app/services/ingestion_service.py] — aioboto3 context manager pattern; DynamoDB `update_item` with `#st` alias; `logger.error` with `extra_data`
- [Source: app/core/config.py:26-29] — `sqs_ingestion_queue_url`, `dynamodb_jobs_table`, `aws_region`, `aws_endpoint_url`
- [Source: app/utils/observability.py] — `get_logger(__name__)` factory
- [Source: tests/services/test_ingestion_service.py] — `_make_aws_mock()` / `_make_db()` mock factory patterns (must follow exactly)
- [Source: _bmad-output/implementation-artifacts/3-1-document-upload-s3-archive-and-sqs-enqueue.md#Dev Notes] — DynamoDB reserved word `status` workaround; import order I001; aioboto3 context manager pattern

---

## Dev Agent Record

### Agent Model Used
claude-sonnet-4-6

### Debug Log References
- ruff SIM117: merged nested `with` statements in test_ingestion_worker.py
- ruff F401: removed unused `PermanentIngestionError` import from ingestion_worker.py (error handled by re-raise, not explicit catch)
- mypy: added `# type: ignore[import-untyped]` for aioboto3; typed `AsyncIOMotorDatabase[Any]`, `dict[str, Any]`

### Completion Notes List
- Added `PERMANENT_INGESTION_ERROR` to `ErrorCode` enum and `PermanentIngestionError(TrueRAGError)` class (http_status=500, worker-only)
- Created `app/workers/` package: `IngestionJobPayload` dataclass (7 fields matching D9 SQS message format), `process_job()` with processing→stub→ready status transitions, `_run_pipeline_stub()` Epic 4 hook
- Created `app/workers/sqs_consumer.py`: `MAX_RECEIVE_COUNT=3`, `run_consumer()` long-poll loop, `_dispatch()` with permanent/transient DLQ logic, `_update_status()` shared helper, `__main__` standalone entry point
- 9 new tests pass (4 ingestion_worker + 5 sqs_consumer); 245 total (236 baseline + 9 new), zero regressions
- ruff clean, mypy strict clean

### File List
- app/core/errors.py (modified)
- app/workers/__init__.py (created)
- app/workers/ingestion_worker.py (created)
- app/workers/sqs_consumer.py (created)
- tests/workers/__init__.py (created)
- tests/workers/test_ingestion_worker.py (created)
- tests/workers/test_sqs_consumer.py (created)

### Change Log
- 2026-04-29: Story 3.2 implemented — SQS consumer worker with full status tracking (processing/ready/failed), DLQ detection via ApproximateReceiveCount, permanent vs transient failure handling, pipeline stub for Epic 4 replacement
