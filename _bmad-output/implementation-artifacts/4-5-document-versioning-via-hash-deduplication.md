# Story 4.5: Document Versioning via Hash Deduplication

Status: done

## Story

As a Tenant Developer,  
I want re-uploading an existing document to create a new version with the old chunks removed,  
so that I can update knowledge base content without accumulating stale vectors across versions.

## Acceptance Criteria

**AC1:** Given a document is uploaded whose content hash matches an existing document for the same agent, when `ingestion_service.py` processes the upload, then a new document record is created with `version` incremented by 1, the previous version's chunks are deleted from the pgvector namespace, the previous version's MongoDB document record is marked archived with its metadata preserved for audit, and the new version's chunks are stored in the pgvector namespace.

**AC2:** Given a document is uploaded whose content hash does not match any existing document for the agent, when the upload is processed, then a new document record is created with `version: 1` and no existing records are modified.

**AC3:** Given a document record in MongoDB, when it is inspected, then it contains a `version` integer field and a `content_hash` field, and all version history for a document is queryable including archived records.

## Tasks / Subtasks

- [x] Extend the document persistence model for versioning and archival metadata (AC: 1, 3)
  - [x] Add `version: int` and `content_hash: str` to `app/models/document.py`.
  - [x] Add explicit archival and lineage fields instead of overloading `DocumentStatus`, for example `archived_at`, `superseded_by_document_id`, and a stable lineage field such as `lineage_id`.
  - [x] Keep `DocumentStatus` focused on ingestion lifecycle (`queued`, `processing`, `ready`, `failed`) so `ingestion_jobs` and status polling do not inherit an `archived` state accidentally.
  - [x] Add Beanie/MongoDB indexes that support:
  - [x] active-document lookup by agent and content hash,
  - [x] history lookup by lineage and version order,
  - [x] list queries that exclude archived records without full collection scans.

- [x] Add upload-time hash detection and version assignment in `app/services/ingestion_service.py` (AC: 1, 2, 3)
  - [x] Compute a deterministic SHA-256 content hash from the uploaded bytes after size validation and before S3/SQS side effects.
  - [x] Look up the latest active document candidate for the same `tenant_id` and `agent_id` using the new indexed fields.
  - [x] When no match exists, create a normal version-1 document record and preserve current endpoint behavior.
  - [x] When a match exists, create a new document record with incremented `version` and lineage linkage while preserving a fresh `document_id`, `job_id`, and S3 key for the new upload.
  - [x] Preserve compensation safety: if downstream persistence or enqueue steps fail, do not leave partially switched version metadata behind.

- [x] Implement safe replacement finalization after successful ingestion, not during initial upload (AC: 1)
  - [x] Do not archive the previous document or delete its vectors in `upload_document()` before the replacement has been embedded and upserted successfully.
  - [x] Update the worker/pipeline path so it can load the persisted document record and use the stored `version` instead of hardcoding `version=1` in chunk metadata.
  - [x] After successful vector upsert for a replacement upload, delete the superseded document's vectors using namespace plus prior `document_id`.
  - [x] Mark the previous document archived only after new vectors are safely stored.
  - [x] Call `await semantic_cache.invalidate(agent_id)` after successful replacement finalization to preserve the explicit future-facing contract from Story 1.9 and architecture guidance.
  - [x] If replacement ingestion fails, leave the prior document active and its vectors intact; only the new document record should move to `failed`.

- [x] Keep existing read and delete flows consistent with archived versions (AC: 1, 3)
  - [x] Ensure `list_documents()` returns active documents only unless a future history endpoint is added.
  - [x] Ensure `get_document_status()` remains correct for the newly created version record and does not regress existing polling semantics.
  - [x] Ensure `delete_document()` behavior is defined for archived records versus active records; at minimum, do not let archival metadata break current ownership and cleanup logic.

- [x] Add focused regression tests for service, worker, and model behavior (AC: 1, 2, 3)
  - [x] Extend `tests/services/test_ingestion_service_dao.py` for no-match uploads, matched uploads with version increment, and enqueue/persistence failure compensation.
  - [x] Extend `tests/workers/test_ingestion_worker_dao.py` for successful replacement finalization and failed replacement preservation of the prior active version.
  - [x] Add model/index assertions in the relevant tests for versioning fields and lineage/history query support.
  - [x] Extend `tests/api/v1/test_documents_dao.py` only where behavior is externally visible, especially that active listings do not surface archived duplicates.

## Dev Notes

### Story Intent and Scope

- This story adds document versioning without changing the external upload contract.
- The high-risk boundary is replacement safety: old vectors must not be removed until the new version is actually ingested.
- This story is not a generic dedup pass across all tenant documents; matching is scoped to the same agent as required by the epic.

### Architecture Guardrails (Must Follow)

- Namespace isolation remains zero-tolerance; any vector deletion or upsert must continue to use `{tenant_id}_{agent_id}` as the hard namespace.  
  [Source: `_bmad-output/planning-artifacts/architecture.md`]
- The architecture explicitly calls out this story: `document.py` needs a `version` field and `ingestion_service.py` needs hash-based deduplication.  
  [Source: `_bmad-output/planning-artifacts/architecture.md`]
- Semantic cache invalidation on document update is an explicit architecture requirement even though the current implementation is a no-op stub.  
  [Source: `_bmad-output/planning-artifacts/architecture.md`, `app/utils/semantic_cache.py`]
- Provider resolution must still flow through registry/dependencies; do not instantiate vector-store implementations directly in service or worker code.  
  [Source: `_bmad-output/planning-artifacts/architecture.md`]

### Codebase Reality and Required Touchpoints

- `DocumentRecord` currently lacks `version`, `content_hash`, lineage, and archival fields.  
  [Source: `app/models/document.py`]
- `upload_document()` currently creates a fresh `document_id`, writes to S3, inserts one document row, creates one ingestion job, and enqueues SQS with no dedup path.  
  [Source: `app/services/ingestion_service.py`]
- The worker currently hardcodes chunk metadata `version=1`; this must be replaced with persisted version data.  
  [Source: `app/pipelines/ingestion/pipeline.py`]
- `semantic_cache.invalidate(agent_id)` already exists as a no-op forward-compatibility stub and is safe to call now.  
  [Source: `app/utils/semantic_cache.py`, `_bmad-output/implementation-artifacts/1-9-semantic-cache-stub.md`]
- Recent Story 4.4 added document-scoped vector deletion; reuse that capability for superseded-version cleanup instead of inventing a new provider path.  
  [Source: `_bmad-output/implementation-artifacts/4-4-document-deletion-with-chunk-cleanup.md`]

### Recommended Implementation Shape

1. Read upload bytes once, validate size/type, and compute `content_hash`.
2. Look up the latest active document in the same agent that should act as the version predecessor.
3. Insert the new versioned document row and ingestion job, keeping the predecessor active for now.
4. Run the normal worker pipeline against the new `document_id`.
5. After successful upsert, archive the predecessor, delete its vectors, and invalidate semantic cache.
6. If worker processing fails, mark only the new version as failed and leave the predecessor unchanged.

This preserves continuity for the active knowledge base and avoids the worst failure mode: deleting the old version before the replacement is usable.

### Inferred Design Decision: Preserve Current `document_id` Semantics

- Inference from current code: `document_id` is a version-specific identifier today. It is used in the upload response, S3 key layout, SQS payload, vector IDs, status polling, and delete flow.
- Because of that existing coupling, the safest implementation is to keep generating a fresh `document_id` for each upload and introduce a separate stable lineage field for version history.
- Do not reinterpret `document_id` into a permanent logical-document key in this story; that would ripple across APIs and worker contracts far beyond the scope of FR16.

### Data and Indexing Guidance

- Use Beanie `Settings.indexes` for compound indexes rather than ad hoc query assumptions.  
  [Source: https://beanie-odm.dev/tutorial/indexes/]
- MongoDB compound indexes help exact-match and prefix queries; they are appropriate for `(tenant_id, agent_id, archived_at, content_hash)` or similar active-document lookups.  
  [Source: https://www.mongodb.com/docs/v8.0/core/indexes/index-types/index-compound/create-compound-index/]
- Partial unique indexes only constrain documents that match the filter expression. Use them carefully; they are not a free substitute for transition-safe versioning because this story temporarily needs both the predecessor and replacement records to coexist during ingestion finalization.  
  [Source: https://www.mongodb.com/docs/manual/core/index-partial/]

### Hashing Guidance

- Python 3.11 includes `hashlib.file_digest()` for efficient file-like hashing, but this service already materializes upload bytes for size checks and S3 upload, so hashing the in-memory bytes once is the simplest consistent path for this story.  
  [Source: https://docs.python.org/3.11/library/hashlib.html]
- Use SHA-256. Do not use MD5 or SHA-1 for this feature.
- Do not hash scrubbed text or parsed content; hash the uploaded binary payload so identical uploads map deterministically before ingestion.

### Regression Risks to Prevent

- Do not add an `archived` member to `DocumentStatus` unless you also want that state leaking into `IngestionJob` records and status polling.
- Do not delete predecessor vectors from inside `upload_document()`; if the worker later fails, the agent would lose its active knowledge base.
- Do not show archived versions in the default document listing; that would create duplicate-looking entries for normal users.
- Do not reintroduce DynamoDB ingestion-job logic. Current architecture and code use MongoDB `ingestion_jobs`, and the older project-context statement is stale on this point.

### Previous Story Intelligence (4.4)

- Story 4.4 already established a safe destructive ordering principle: validate ownership first, then clean vectors before deleting Mongo records.
- The new story should apply the same rigor but with an even stricter rule: predecessor cleanup happens only after replacement success.
- Reuse the provider capability that already deletes vectors by `document_id` in a namespace.

[Source: `_bmad-output/implementation-artifacts/4-4-document-deletion-with-chunk-cleanup.md`]

### Git Intelligence (Recent Patterns)

- Recent commits show the ingestion path evolving through service-layer orchestration plus thin routes.
- Recent pgvector work already added document-scoped deletion support; this story should extend that path rather than bypassing it.

[Source: `git log --oneline -5`]

### Latest Technical Information (Verified on 2026-05-02)

- Python 3.11's `hashlib.file_digest()` is available for binary file-like objects if the upload flow is later refactored away from eager byte reads.  
  [Source: https://docs.python.org/3.11/library/hashlib.html]
- Beanie supports multi-field indexes and explicit `IndexModel` declarations via `Settings.indexes`, which is the right mechanism for version-history and active-document lookup indexes.  
  [Source: https://beanie-odm.dev/tutorial/indexes/]
- MongoDB compound indexes improve performance for exact and prefix queries, which matters for agent-scoped active-document lookups and lineage history queries.  
  [Source: https://www.mongodb.com/docs/v8.0/core/indexes/index-types/index-compound/create-compound-index/]
- MongoDB partial indexes with unique constraints only apply to indexed documents, so they must not be used naively in a workflow that intentionally overlaps predecessor and replacement records during switchover.  
  [Source: https://www.mongodb.com/docs/manual/core/index-partial/]

### Suggested File Touchpoints

- `app/models/document.py`
- `app/services/ingestion_service.py`
- `app/workers/ingestion_worker.py`
- `app/pipelines/ingestion/pipeline.py`
- `app/db/dao/document_dao.py`
- `tests/services/test_ingestion_service_dao.py`
- `tests/workers/test_ingestion_worker_dao.py`
- `tests/api/v1/test_documents_dao.py`

### Open Question

- The epic wording says history should be queryable "by `document_id`", but the existing codebase already uses `document_id` as a per-upload identifier. This story context recommends adding a lineage field and preserving current `document_id` behavior. If product wants API-visible history under a stable document key, that should be clarified explicitly before changing external contracts.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 4.5`]
- [Source: `_bmad-output/planning-artifacts/architecture.md`]
- [Source: `_bmad-output/planning-artifacts/prd.md`]
- [Source: `_bmad-output/project-context.md`]
- [Source: `_bmad-output/implementation-artifacts/4-4-document-deletion-with-chunk-cleanup.md`]
- [Source: `_bmad-output/implementation-artifacts/1-9-semantic-cache-stub.md`]
- [Source: `app/models/document.py`]
- [Source: `app/services/ingestion_service.py`]
- [Source: `app/pipelines/ingestion/pipeline.py`]
- [Source: `app/workers/ingestion_worker.py`]
- [Source: `app/utils/semantic_cache.py`]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- 2026-05-02: Story context creation (`bmad-create-story`)

### Completion Notes List

- Story context generated for versioned document replacement with upload-time hash detection and post-ingestion switchover guardrails.
- Added explicit direction to keep `document_id` version-specific and introduce lineage metadata for history queries.
- Added architecture-backed requirement to invalidate semantic cache after successful replacement finalization.
- Flagged the stale project-context DynamoDB note and directed implementation to current MongoDB ingestion-job architecture.
- Implemented `DocumentRecord` versioning and archival fields plus compound indexes for active lookup, lineage history, and active-list filtering.
- Added upload-time SHA-256 hash detection with version assignment (`v1` on no match, incremented version with lineage on match).
- Updated worker finalization to archive predecessor only after successful replacement ingestion, delete predecessor vectors, and invalidate semantic cache.
- Updated ingestion pipeline to use persisted document version in chunk metadata instead of a hardcoded value.
- Added regression coverage for service, worker, and pipeline version/finalization paths; targeted suites pass.

### File List

- _bmad-output/implementation-artifacts/4-5-document-versioning-via-hash-deduplication.md
- app/models/document.py
- app/services/ingestion_service.py
- app/workers/ingestion_worker.py
- app/pipelines/ingestion/pipeline.py
- tests/services/test_ingestion_service_dao.py
- tests/workers/test_ingestion_worker_dao.py
- tests/pipelines/ingestion/test_pipeline.py

### Change Log

- 2026-05-02: Implemented Story 4.5 document versioning, replacement finalization safety, and regression tests.

## Completion Note

Ultimate context engine analysis completed - comprehensive developer guide created.
