# Story 3.4: PII Scrubbing at Ingestion

Status: done

## Story

As a Tenant Developer,
I want PII automatically removed from every document before any chunk is stored,
so that no personal data reaches the vector store or LLM context, enforcing zero-tolerance compliance (FR18, NFR9).

## Acceptance Criteria

**AC1:** Given a document with PII (names, emails, phone numbers) is being processed by the ingestion worker, when `scrub_pii()` is called on extracted raw text before chunking begins, then all PII entities are replaced with anonymised placeholders; the scrubbed text — never the original — is passed to the chunking step.

**AC2:** Given `scrub_pii()` is called during ingestion, when the call site is inspected, then it is an explicit call in `app/pipelines/ingestion/pipeline.py` between the parse step and the chunk step; not applied via middleware or decorator that could be bypassed.

**AC3:** Given PII scrubbing runs on a document, when a structured log entry is emitted, then the log includes `operation: pii_scrub`, `tenant_id`, `agent_id`, `document_id`, and `latency_ms`; the original or scrubbed text content is never written to any log.

## Tasks / Subtasks

- [x] Task 1: Create `app/pipelines/ingestion/pipeline.py` (AC1, AC2, AC3)
  - [x] Define `async def run_ingestion_pipeline(payload: IngestionJobPayload, aws_session: aioboto3.Session, settings: Settings) -> None`
  - [x] Step 1 — `_download_from_s3`: async; fetch bytes via `aws_session.client("s3")` using `payload.s3_key` and `settings.s3_document_bucket`
  - [x] Step 2 — `_extract_text`: synchronous; `content.decode("utf-8", errors="replace")` for all file types (txt/md exact; pdf/docx best-effort stub replaced by Epic 4)
  - [x] Step 3 — `_scrub_with_logging`: call `scrub_pii(raw_text, document_id=payload.document_id)` from `app.utils.pii`; capture `latency_ms` via `time.perf_counter()`; emit log with `operation: pii_scrub`, `tenant_id`, `agent_id`, `document_id`, `latency_ms`; NEVER log text content
  - [x] Step 4 — `_chunk_embed_upsert_stub`: log `"chunking_not_yet_implemented"` with `job_id`, `document_id`, `tenant_id`; return `None`
  - [x] `ProviderUnavailableError` from `scrub_pii()` must NOT be caught — propagate as-is for SQS retry

- [x] Task 2: Move `IngestionJobPayload` to `app/models/ingestion_job.py` to prevent circular import (AC1)
  - [x] Add `IngestionJobPayload` dataclass to `app/models/ingestion_job.py`
  - [x] Update `app/workers/ingestion_worker.py` import: `from app.models.ingestion_job import IngestionJobPayload`
  - [x] Update any tests that import `IngestionJobPayload` from `app.workers.ingestion_worker`

- [x] Task 3: Update `app/workers/ingestion_worker.py` (AC1)
  - [x] Import `run_ingestion_pipeline` from `app.pipelines.ingestion.pipeline`
  - [x] In `process_job`, replace `await _run_pipeline_stub(payload, aws_session, settings)` with `await run_ingestion_pipeline(payload, aws_session, settings)`
  - [x] Remove `_run_pipeline_stub` function entirely

- [x] Task 4: Update `tests/workers/test_ingestion_worker_dao.py` to fix broken patch target (regression)
  - [x] Change `patch("app.workers.ingestion_worker._run_pipeline_stub", ...)` to `patch("app.workers.ingestion_worker.run_ingestion_pipeline", ...)`
  - [x] Update import: `from app.models.ingestion_job import IngestionJobPayload` if needed

- [x] Task 5: Create `tests/pipelines/ingestion/__init__.py` and `tests/pipelines/ingestion/test_pipeline.py` (AC1, AC2, AC3)
  - [x] Test: `run_ingestion_pipeline` calls `scrub_pii` with text extracted from S3 content
  - [x] Test: scrubbed text (not original) is passed to chunk stub
  - [x] Test: `ProviderUnavailableError` from `scrub_pii` propagates without being wrapped
  - [x] Test: log call includes `tenant_id`, `agent_id`, `document_id`, `latency_ms`; text content absent from all log calls
  - [x] Test: S3 `get_object` failure propagates as-is (transient, SQS retries)

- [x] Task 6: Verify no regressions
  - [x] Run full test suite; all pre-existing tests pass

### Review Findings

- [x] [Review][Patch] Fragile text-absence assertion uses `str(call_args_list)` substring search — repr-escaping can produce false negatives [tests/pipelines/ingestion/test_pipeline.py:134-136]
- [x] [Review][Defer] S3 object body fully buffered with no size guard — OOM risk on large files [app/pipelines/ingestion/pipeline.py:35] — deferred, pre-existing design gap
- [x] [Review][Defer] `_extract_text` ignores `file_type`, always decodes bytes as UTF-8 — binary PDF/DOCX produces garbage text [app/pipelines/ingestion/pipeline.py:38-40] — deferred, intentional Epic 4 stub
- [x] [Review][Defer] `IngestionJobPayload.timestamp` accepts any string — no ISO-8601 or timezone validation [app/models/ingestion_job.py:17] — deferred, spec-compliant as-is
- [x] [Review][Defer] `_scrub_with_logging` omits `s3_key` and `job_id` — incident triage gap [app/pipelines/ingestion/pipeline.py:47-58] — deferred, fields not required by AC3
- [x] [Review][Defer] `_download_from_s3` has no request timeout — stalled S3 endpoint blocks worker indefinitely [app/pipelines/ingestion/pipeline.py:29-35] — deferred, infrastructure-level concern
- [x] [Review][Defer] `_get_engines()` lazy-init failure in `scrub_pii` propagates as raw `Exception`, not `ProviderUnavailableError` [app/utils/pii.py] — deferred, pre-existing in pii.py
- [x] [Review][Defer] `payload.s3_key` passed verbatim to S3 `get_object` — no cross-tenant namespace enforcement [app/pipelines/ingestion/pipeline.py:34] — deferred, validation belongs in SQS consumer upstream
- [x] [Review][Defer] DAO status-update calls sit before `try` block in `process_job` — DAO failure leaves document stuck in `queued` [app/workers/ingestion_worker.py] — deferred, pre-existing pattern

## Dev Notes

### Pipeline Architecture — Exact Location Constraint

Architecture spec mandates this exact flow:
```
worker dequeues → ingestion_pipeline → parse → pii.scrub_pii() → chunker → embedder → vector store upsert()
```
The PII scrub call must be in `app/pipelines/ingestion/pipeline.py` — explicit, not via middleware or decorator. This is a zero-tolerance requirement.
[Source: `_bmad-output/planning-artifacts/architecture.md#Request Flow`]
[Source: `_bmad-output/planning-artifacts/architecture.md#Cross-Cutting Concerns`]

### Circular Import — Must Resolve Before Writing pipeline.py

`IngestionJobPayload` is currently defined in `app/workers/ingestion_worker.py`. `pipeline.py` needs it, and `ingestion_worker.py` will import `run_ingestion_pipeline` from `pipeline.py`. This creates a circular import. **Resolution:** Move `IngestionJobPayload` dataclass to `app/models/ingestion_job.py` (which already contains `IngestionJob` Beanie document). Both `pipeline.py` and `ingestion_worker.py` then import from a neutral module.

```python
# app/models/ingestion_job.py — ADD at bottom
from dataclasses import dataclass

@dataclass
class IngestionJobPayload:
    job_id: str
    tenant_id: str
    agent_id: str
    document_id: str
    s3_key: str
    file_type: str
    timestamp: str
```

### pipeline.py — Reference Implementation Skeleton

```python
import time
import aioboto3
from app.core.config import Settings
from app.models.ingestion_job import IngestionJobPayload
from app.utils.observability import get_logger
from app.utils.pii import scrub_pii

logger = get_logger(__name__)


async def run_ingestion_pipeline(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    content = await _download_from_s3(payload, aws_session, settings)
    raw_text = _extract_text(content, payload.file_type)
    scrubbed_text = _scrub_with_logging(raw_text, payload)
    await _chunk_embed_upsert_stub(scrubbed_text, payload)


async def _download_from_s3(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> bytes:
    async with aws_session.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as s3:
        response = await s3.get_object(Bucket=settings.s3_document_bucket, Key=payload.s3_key)
        return await response["Body"].read()


def _extract_text(content: bytes, file_type: str) -> str:
    # txt/md: exact UTF-8; pdf/docx: best-effort stub (Epic 4 replaces with real parsers)
    return content.decode("utf-8", errors="replace")


def _scrub_with_logging(raw_text: str, payload: IngestionJobPayload) -> str:
    t0 = time.perf_counter()
    scrubbed = scrub_pii(raw_text, document_id=payload.document_id)
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "pii_scrub",
        extra={
            "operation": "pii_scrub",
            "extra_data": {
                "tenant_id": payload.tenant_id,
                "agent_id": payload.agent_id,
                "document_id": payload.document_id,
                "latency_ms": latency_ms,
            },
        },
    )
    return scrubbed


async def _chunk_embed_upsert_stub(scrubbed_text: str, payload: IngestionJobPayload) -> None:
    logger.info(
        "chunking_not_yet_implemented",
        extra={
            "extra_data": {
                "job_id": payload.job_id,
                "document_id": payload.document_id,
                "tenant_id": payload.tenant_id,
            }
        },
    )
```

### PII Scrubbing — Critical Rules

1. `scrub_pii()` is **synchronous** — no `await`
2. `ProviderUnavailableError` from `scrub_pii()` = **transient failure** — do NOT catch in `pipeline.py`; must bubble up to `process_job` → SQS retry path (3 attempts → DLQ)
3. Text content — neither `raw_text` nor `scrubbed` — must **NEVER** appear in any log
4. `scrub_pii()` already emits its own internal `pii_scrub` log with `entities_found` and `document_id`. `_scrub_with_logging` emits the pipeline-level log with `tenant_id`, `agent_id`, `latency_ms` — these are separate, complementary log entries

### Worker Update — Patch Target Change

`test_ingestion_worker_dao.py` currently patches:
```python
patch("app.workers.ingestion_worker._run_pipeline_stub", AsyncMock(return_value=None))
```
After Task 3, `_run_pipeline_stub` is gone. The test breaks with `AttributeError` at collection. Update to:
```python
patch("app.workers.ingestion_worker.run_ingestion_pipeline", AsyncMock(return_value=None))
```

### Test Pattern for pipeline tests

```python
@pytest.mark.asyncio
async def test_pipeline_calls_scrub_pii_with_extracted_text() -> None:
    with (
        patch(
            "app.pipelines.ingestion.pipeline._download_from_s3",
            AsyncMock(return_value=b"John Smith works here"),
        ),
        patch(
            "app.pipelines.ingestion.pipeline.scrub_pii",
            return_value="<PERSON> works here",
        ) as mock_scrub,
        patch(
            "app.pipelines.ingestion.pipeline._chunk_embed_upsert_stub",
            AsyncMock(return_value=None),
        ),
    ):
        await run_ingestion_pipeline(_make_payload(), AsyncMock(), _make_settings())
    mock_scrub.assert_called_once()
    assert mock_scrub.call_args[0][0] == "John Smith works here"
```

For log content test — patch `app.pipelines.ingestion.pipeline.logger` and assert `info` called with keys `tenant_id`, `agent_id`, `document_id`, `latency_ms` in `extra["extra_data"]`, and that neither `raw_text` nor scrubbed text appear in any call args.

### S3 Download Pattern

Follows the established `aioboto3` async context manager pattern from `app/services/ingestion_service.py`. S3 errors propagate as-is (transient — SQS retries handle them).

### Existing Files to NOT Touch

- `app/utils/pii.py` — do not modify; `scrub_pii()` interface is stable
- `tests/utils/test_pii.py` — do not modify
- `app/services/ingestion_service.py` — no changes needed for this story
- `app/models/document.py` — no changes needed

### Deferred Work (Do NOT Fix in This Story)

From `deferred-work.md` (code review of 1-5):
- Thread-safe lazy init of PII engines (`pii.py:16-18`) — TOCTOU under `run_in_executor`
- Hardcoded `language="en"` in `scrub_pii()`
- `anonymized.text` could be `None` → returns `"None"` string

### Project Structure Notes

- `app/pipelines/ingestion/` directory EXISTS (from scaffold)
- `app/pipelines/ingestion/__init__.py` EXISTS (empty)
- `app/pipelines/ingestion/pipeline.py` does NOT exist — create it
- `tests/pipelines/` EXISTS with `__init__.py`
- `tests/pipelines/ingestion/` does NOT exist — create `__init__.py` + `test_pipeline.py`
- `tests/workers/test_ingestion_worker.py` is already skipped (legacy DynamoDB tests) — do not un-skip

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`] — User story and acceptance criteria
- [Source: `_bmad-output/planning-artifacts/architecture.md#Cross-Cutting Concerns`] — PII scrubbing explicit call site requirement; must not be bypassable
- [Source: `_bmad-output/planning-artifacts/architecture.md#Request Flow`] — `parse → pii.scrub_pii() → chunker → embedder → vector upsert` exact pipeline sequence
- [Source: `app/utils/pii.py`] — `scrub_pii(text, *, document_id=None) -> str`; raises `ProviderUnavailableError` on Presidio failure; already logs `pii_scrub` internally
- [Source: `app/workers/ingestion_worker.py`] — `process_job()` and `_run_pipeline_stub()` (to be removed)
- [Source: `tests/workers/test_ingestion_worker_dao.py`] — patch target `_run_pipeline_stub` must be updated to `run_ingestion_pipeline`
- [Source: `app/models/ingestion_job.py`] — move `IngestionJobPayload` here to avoid circular import
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md`] — deferred PII items from story 1-5 review; do not address here

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- Moved `IngestionJobPayload` dataclass from `app/workers/ingestion_worker.py` to `app/models/ingestion_job.py` to break circular import
- Created `app/pipelines/ingestion/pipeline.py` with exact 4-step flow: download → extract → scrub+log → chunk stub
- `_scrub_with_logging` calls `scrub_pii()` (synchronous, no await), captures `latency_ms` via `time.perf_counter()`, emits structured log with `operation: pii_scrub`, `tenant_id`, `agent_id`, `document_id`, `latency_ms`; text content never logged
- `ProviderUnavailableError` propagates uncaught from pipeline to `process_job` → SQS retry path
- Updated `ingestion_worker.py`: removed `_run_pipeline_stub`, now calls `run_ingestion_pipeline`
- Updated `test_ingestion_worker_dao.py`: patch target and import fixed
- 5 new tests in `tests/pipelines/ingestion/test_pipeline.py` covering all ACs; 152 total tests pass

### File List

- `app/models/ingestion_job.py` (modified — added `IngestionJobPayload` dataclass)
- `app/pipelines/ingestion/pipeline.py` (created)
- `app/workers/ingestion_worker.py` (modified — removed stub, added pipeline import)
- `tests/workers/test_ingestion_worker_dao.py` (modified — fixed patch target and import)
- `tests/pipelines/ingestion/__init__.py` (created)
- `tests/pipelines/ingestion/test_pipeline.py` (created)

## Change Log

- 2026-05-01: Implemented PII scrubbing at ingestion pipeline (story 3-4). Created `app/pipelines/ingestion/pipeline.py` with explicit `scrub_pii()` call between parse and chunk steps. Moved `IngestionJobPayload` to `app/models/ingestion_job.py`. 152 tests pass.
