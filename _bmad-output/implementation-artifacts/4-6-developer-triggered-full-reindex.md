# Story 4.6: Developer-Triggered Full Reindex

## Story

**Status:** done
**Date:** 2026-05-02

As a Tenant Developer,
I want to trigger a full reindex of all documents in my agent after a pipeline configuration change, with the semantic cache cleared first,
so that existing chunks are regenerated with the new strategy and no stale cached responses are served from the rebuilt knowledge base (FR17).

---

## Acceptance Criteria

**AC1:** Given `POST /v1/agents/{agent_id}/reindex` for an agent with ingested documents, when the request is processed, then all existing chunks for the agent are deleted from the pgvector namespace; all `ready` documents are re-enqueued to SQS for re-processing through the full ingestion pipeline with the current agent config; HTTP 202 Accepted is returned with a count of documents re-enqueued.

**AC2:** Given a reindex is triggered for an agent, when the reindex begins, then `semantic_cache.invalidate(agent_id)` from `app/utils/semantic_cache.py` is called before any re-enqueueing occurs; prior to Epic 8 this is a no-op stub (Story 1.9); from Epic 8 onwards it clears cached responses — call sites are identical in both cases.

**AC3:** Given the reindex is triggered, when document status records are updated, then all affected MongoDB document records are reset to `status: queued` and new IngestionJob records are created (with fresh `job_id`) before enqueueing begins.

**AC4:** Given `POST /v1/agents/{agent_id}/reindex` for an agent belonging to a different tenant, when the request is processed, then HTTP 403 Forbidden is returned; no reindex occurs.

**AC5:** Given an agent with zero `ready` documents (all are `queued`, `processing`, `failed`, or `archived`), when the request is processed, then HTTP 202 is returned with `enqueued_count: 0`; no SQS messages are sent.

---

## Tasks / Subtasks

### Task 1: Add `ReindexResponse` model to `app/models/document.py`
- [x] Add `class ReindexResponse(BaseModel): enqueued_count: int` after existing response models
- [x] Import in `app/api/v1/documents.py`

### Task 2: Implement `reindex_agent` in `app/services/ingestion_service.py`
- [x] Add `from app.models.document import ReindexResponse` to imports
- [x] Add `from app.utils import semantic_cache` import (already present — verify it is)
- [x] Implement `async def reindex_agent(agent_id, tenant_id, aws_session, settings) -> ReindexResponse`
  - Call `agent_service.get_agent(agent_id, tenant_id)` first — raises `AgentNotFoundError` (404) or `ForbiddenError` (403) automatically
  - Build `namespace = f"{tenant_id}_{agent_id}"`
  - Call `await semantic_cache.invalidate(agent_id)` — call site identical before/after Epic 8
  - Call `await get_vector_store(agent.vector_store).delete_namespace(namespace)` — deletes ALL chunks
  - Find all reindexable docs: `document_dao.find({"tenant_id": tenant_id, "agent_id": agent_id, "status": DocumentStatus.ready, "archived_at": None})`
  - For each doc: generate `new_job_id = str(ObjectId())`; `await ingestion_job_dao.insert_one(IngestionJob(...))` ; `await document_dao.update({"document_id": doc.document_id}, {"status": DocumentStatus.queued, "job_id": new_job_id, "error_reason": None})`
  - Open single SQS client context and enqueue each doc as per existing SQS message shape
  - Log `reindex_complete` with `enqueued_count`
  - Return `ReindexResponse(enqueued_count=len(docs))`

### Task 3: Add `POST /{agent_id}/reindex` route to `app/api/v1/documents.py`
- [x] Add `ReindexResponse` to the import from `app.models.document`
- [x] Add route handler — delegates entirely to `ingestion_service.reindex_agent`
- [x] Status `HTTP_202_ACCEPTED`, `response_model=ReindexResponse`
- [x] Route must come BEFORE any parametric routes that could shadow it (no conflict risk here — `/reindex` is a fixed suffix)

### Task 4: Tests in `tests/services/test_ingestion_service_dao.py`
- [x] `test_reindex_agent_happy_path` — agent with 2 ready docs; assert `delete_namespace` called once with correct namespace; assert 2 `insert_one` (IngestionJob), 2 `update` (document reset to queued), 2 SQS `send_message`; returns `enqueued_count=2`
- [x] `test_reindex_agent_empty_agent` — 0 ready docs; assert `delete_namespace` called; no `insert_one`/`send_message`; returns `enqueued_count=0`
- [x] `test_reindex_agent_skips_archived_and_non_ready_docs` — mix of archived, failed, queued docs; all skipped; `enqueued_count=0`
- [x] `test_reindex_agent_forbidden` — `agent_service.get_agent` raises `ForbiddenError`; `delete_namespace` not called; error propagates

### Review Findings
- [x] [Review][Patch] Reindex leaves historical ingestion jobs behind, so document deletion no longer cleans up all jobs [app/services/ingestion_service.py:347]
- [x] [Review][Patch] Reindex can strand documents in `queued` with no SQS message if enqueue fails mid-loop after namespace deletion [app/services/ingestion_service.py:401]

---

## Dev Notes

### Story Intent and Scope

This story wires `POST /v1/agents/{agent_id}/reindex` end-to-end. It is a **synchronous HTTP endpoint** that:
1. Verifies tenant ownership
2. Clears the semantic cache (no-op now, real in Epic 8)
3. Nukes all pgvector chunks for the namespace
4. Finds all `ready` + non-archived documents
5. Creates fresh IngestionJob records for each, resets document status to `queued`
6. Enqueues each to SQS (same message shape as `upload_document`)
7. Returns 202 + count

No new background task or worker change is needed — the existing `ingestion_worker.process_job` handles re-ingestion identically to a fresh upload.

### Architecture Guardrails (Must Follow)

- **Namespace format**: `f"{tenant_id}_{agent_id}"` — identical to what pipeline uses for upsert. Do not deviate.
- **`delete_namespace` exists**: `PgVectorStore.delete_namespace(namespace: str)` at `app/providers/vector_stores/pgvector.py:121` — `DELETE FROM {table} WHERE namespace = $1`. Use it. Do not try to delete per-document.
- **Service layer owns all logic**: route handler is thin delegator. No business logic in the route.
- **`agent_service.get_agent` is the ownership gate**: it raises `AgentNotFoundError` (404) or `ForbiddenError` (403) automatically. Do not replicate this check manually.
- **SQS message shape** (must match what `ingestion_worker` deserializes via `IngestionJobPayload`):
  ```json
  {
    "job_id": "<new_job_id>",
    "tenant_id": "...",
    "agent_id": "...",
    "document_id": "...",
    "s3_key": "...",
    "file_type": "...",
    "timestamp": "<ISO datetime>"
  }
  ```
  See `ingestion_service.upload_document` lines ~164–175 for exact pattern.
- **`BaseDAO.update(query, dict)` is a bulk op**: `self._model.find(query).update({"$set": dict})` updates ALL matching documents. However, for reindex we need per-document `job_id` updates, so iterate with per-document `update({"document_id": doc.document_id}, {...})` — this is correct and intentional.
- **`BaseDAO` has no `update_many` returning docs** — use `find()` + iterate. The `update()` method with an individual doc filter is the right call.
- **Semantic cache call site**: `await semantic_cache.invalidate(agent_id)` — module-level import `from app.utils import semantic_cache`, not `from app.utils.semantic_cache import invalidate`. Match existing worker pattern exactly:
  ```python
  from app.utils import semantic_cache
  # ...
  await semantic_cache.invalidate(agent_id)
  ```

### Codebase Reality and Required Touchpoints

**Files to modify:**
- `app/models/document.py` — add `ReindexResponse(BaseModel)` after `DocumentListResponse`
- `app/services/ingestion_service.py` — add `reindex_agent()` function
- `app/api/v1/documents.py` — add route + import `ReindexResponse`
- `tests/services/test_ingestion_service_dao.py` — add reindex tests

**No changes needed to:**
- `app/workers/ingestion_worker.py` — worker processes reindex jobs identically to fresh uploads
- `app/pipelines/ingestion/pipeline.py` — pipeline unchanged
- `app/providers/vector_stores/pgvector.py` — `delete_namespace` already implemented
- `app/utils/semantic_cache.py` — stub already exists with correct signature

### Recommended Implementation Shape

**`app/models/document.py`** — add after `DocumentListResponse`:
```python
class ReindexResponse(BaseModel):
    enqueued_count: int
```

**`app/services/ingestion_service.py`** — new function (add to existing imports: `ReindexResponse` from models, verify `semantic_cache` is imported):
```python
async def reindex_agent(
    agent_id: str,
    tenant_id: str,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> ReindexResponse:
    agent = await agent_service.get_agent(agent_id, tenant_id)
    namespace = f"{tenant_id}_{agent_id}"

    await semantic_cache.invalidate(agent_id)

    vector_store = get_vector_store(agent.vector_store)
    await vector_store.delete_namespace(namespace)

    docs = await document_dao.find(
        {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "status": DocumentStatus.ready,
            "archived_at": None,
        }
    )

    now = datetime.now(UTC)
    async with aws_session.client(
        "sqs",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as sqs:
        for doc in docs:
            new_job_id = str(ObjectId())
            await ingestion_job_dao.insert_one(
                IngestionJob(
                    job_id=new_job_id,
                    document_id=doc.document_id,
                    tenant_id=tenant_id,
                    status=DocumentStatus.queued,
                )
            )
            await document_dao.update(
                {"document_id": doc.document_id},
                {"status": DocumentStatus.queued, "job_id": new_job_id, "error_reason": None},
            )
            await sqs.send_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                MessageBody=json.dumps(
                    {
                        "job_id": new_job_id,
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "document_id": doc.document_id,
                        "s3_key": doc.s3_key,
                        "file_type": doc.file_type,
                        "timestamp": now.isoformat(),
                    }
                ),
            )

    logger.info(
        "reindex_complete",
        extra={
            "operation": "reindex_agent",
            "extra_data": {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "enqueued_count": len(docs),
            },
        },
    )
    return ReindexResponse(enqueued_count=len(docs))
```

**`app/api/v1/documents.py`** — add route (place before the delete route to avoid any future routing confusion):
```python
@router.post(
    "/{agent_id}/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReindexResponse,
)
async def reindex_agent_route(
    agent_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> ReindexResponse:
    return await ingestion_service.reindex_agent(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        aws_session=request.app.state.aws_session,
        settings=get_settings(),
    )
```

### Why Fresh `job_id` Per Document (Not Reset Existing)

Each `ready` document gets a brand-new `IngestionJob` record (new `job_id`), and `document.job_id` is updated to point to it. Old job records become historical orphans (cleaned up on eventual document deletion via `delete_many`). Rationale:
- Old job has `status: ready` — resetting it to `queued` would work, but creates confusing history (the old job_id predates the reindex trigger)
- New job gives `get_document_status` a clean audit trail for the reindex run
- Consistent with `upload_document` pattern: each processing cycle produces a new `IngestionJob`

### `_finalize_replacement_if_needed` — Safe Under Reindex

The worker calls `_finalize_replacement_if_needed(document, payload, agent.vector_store)` after pipeline success. For reindex documents:
- If `doc.version == 1`: function returns immediately (`if document.version <= 1: return`)
- If `doc.version > 1`: function queries for predecessor with `{"archived_at": None, "version": version-1}`. The predecessor was archived in Story 4.5 (`archived_at` is set). Query returns `None` → function returns. No accidental deletion.

No regression risk from this code path.

### Regression Risks to Prevent

- **Do NOT query `status: DocumentStatus.ready` without also filtering `archived_at: None`** — archived documents can also have `status: ready`. The filter must include both.
- **Do NOT call `vector_store.delete_document(namespace, doc_id)` per document** — use `delete_namespace(namespace)` for the full wipe. Calling per-document on 100 docs would be 100 DB deletes vs 1.
- **Do NOT open a new SQS client per document** — open once outside the loop, enqueue inside. See `upload_document` for the single-client pattern within a `try`/`except` block.
- **Do NOT skip the `semantic_cache.invalidate` call** — it must always be called before re-enqueueing, even though it's a no-op now. Epic 8 will provide the real implementation at the same call site.
- **Do NOT mutate the existing `ingestion_service.upload_document` flow** — reindex is purely additive.

### Previous Story Intelligence (4.5)

- 4.5 established `DocumentRecord.archived_at` (non-None = archived). The reindex `find` query MUST include `"archived_at": None` to exclude archived predecessor versions.
- 4.5 verified that `document_dao.update()` with individual `document_id` filters works correctly.
- 4.5 confirmed test pattern: `patch("app.services.ingestion_service.document_dao.find", AsyncMock(return_value=[...]))` is correct mock path.
- 4.5 files modified: `app/models/document.py`, `app/services/ingestion_service.py`, `app/workers/ingestion_worker.py`, `app/pipelines/ingestion/pipeline.py` — reindex only touches the first two plus routes.

### Git Intelligence (Recent Patterns)

- All 4.x stories follow: thin route → service function → DAO + provider calls
- Logging: `logger.info("snake_case_op", extra={"operation": "fn_name", "extra_data": {...}})` — match this exactly
- Imports in service: `from bson import ObjectId`, `from datetime import UTC, datetime`, `import json` — already present in `ingestion_service.py`; do not add duplicate imports
- Tests use `@pytest.mark.asyncio` + `patch()` context managers (parenthesized multi-patch style from Python 3.10+)

### Suggested File Touchpoints

| File | Change |
|------|--------|
| `app/models/document.py` | Add `ReindexResponse(BaseModel)` |
| `app/services/ingestion_service.py` | Add `reindex_agent()` function |
| `app/api/v1/documents.py` | Add `POST /{agent_id}/reindex` route + import |
| `tests/services/test_ingestion_service_dao.py` | Add 4 new test functions |

### References

- Story 4.5 (predecessor patterns, archive filter): `_bmad-output/implementation-artifacts/4-5-document-versioning-via-hash-deduplication.md`
- Story 4.4 (delete_document pattern): `_bmad-output/implementation-artifacts/4-4-document-deletion-with-chunk-cleanup.md`
- `delete_namespace` impl: `app/providers/vector_stores/pgvector.py:121`
- SQS enqueue pattern: `app/services/ingestion_service.py` — `upload_document` function, lines ~157–200
- Semantic cache stub: `app/utils/semantic_cache.py` — `async def invalidate(agent_id: str) -> None`
- `BaseDAO.update` is bulk: `app/db/base_dao.py:30` — `self._model.find(query).update({$set: ...})`
- Worker safe for reindex: `app/workers/ingestion_worker.py` — `_finalize_replacement_if_needed`
- FR17: `_bmad-output/planning-artifacts/epics.md:38`

---

## Dev Agent Record

### Agent Model Used
GPT-5 (Codex)

### Debug Log References
- `.venv/bin/python -m pytest tests/services/test_ingestion_service_dao.py`
- `.venv/bin/python -m pytest`
- `.venv/bin/python -m ruff check /home/akash/workspace/products/true-ecosystem/truerag` (reports pre-existing repo lint issues outside this story's scope)

### Completion Notes List
- Implemented `ReindexResponse` model and exposed it via documents API typing.
- Added `ingestion_service.reindex_agent()` with required sequence: tenant ownership check, semantic cache invalidation, namespace deletion, ready+non-archived document selection, fresh ingestion job creation, per-document status reset to queued, and SQS re-enqueue.
- Added `POST /v1/agents/{agent_id}/reindex` route delegating to service and returning HTTP 202 with enqueue count.
- Added four DAO-level service tests covering happy path, empty set, filtering contract validation (`status=ready` + `archived_at=None`), and forbidden propagation.
- Full test suite passed: `201 passed, 9 skipped`.

### File List
- `app/models/document.py`
- `app/services/ingestion_service.py`
- `app/api/v1/documents.py`
- `tests/services/test_ingestion_service_dao.py`
- `_bmad-output/implementation-artifacts/4-6-developer-triggered-full-reindex.md`

### Change Log
- 2026-05-02: Implemented Story 4.6 end-to-end (reindex service, route, model, and tests); validated with targeted and full test suites; status set to `review`.
