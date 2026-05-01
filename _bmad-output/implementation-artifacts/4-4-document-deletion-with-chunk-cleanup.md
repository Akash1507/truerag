# Story 4.4: Document Deletion with Chunk Cleanup

Status: done

## Story

As a Tenant Developer,  
I want to delete a specific document and all its associated chunks from my agent's namespace,  
so that stale or unwanted documents are fully removed from the knowledge base with no residual vectors.

## Acceptance Criteria

**AC1:** Given `DELETE /v1/agents/{agent_id}/documents/{document_id}` for a document belonging to the calling tenant's agent, when the request is processed, then all vectors for that `document_id` are deleted from the pgvector namespace, the MongoDB `documents` record is deleted, the MongoDB `ingestion_jobs` record for the document is deleted, and HTTP 204 No Content is returned only after deletions complete.

**AC2:** Given deletion of a document belonging to a different tenant, when the request is processed, then HTTP 403 Forbidden is returned and no deletions occur.

**AC3:** Given deletion of a non-existent document ID, when the request is processed, then HTTP 404 Not Found is returned.

## Tasks / Subtasks

- [x] Add the document delete route and service wiring (AC: 1, 2, 3)
  - [x] Add `DELETE /v1/agents/{agent_id}/documents/{document_id}` to `app/api/v1/documents.py` with `status_code=status.HTTP_204_NO_CONTENT`.
  - [x] Add `ingestion_service.delete_document(...)` and call it from the route.
  - [x] Keep router thin: auth via `get_current_tenant`, service call only, no business logic in router.

- [x] Implement tenant-safe document lookup and authorization guard (AC: 2, 3)
  - [x] In `ingestion_service.delete_document`, load document via `document_dao.find_one({"document_id": document_id})`.
  - [x] Raise `DocumentNotFoundError` when record is missing.
  - [x] Raise `ForbiddenError` when tenant or agent ownership mismatch.

- [x] Implement namespace-scoped vector cleanup by `document_id` (AC: 1)
  - [x] Resolve agent via `agent_service.get_agent(agent_id, tenant_id)` and derive namespace as `f"{tenant_id}_{agent_id}"`.
  - [x] Add a `PgVectorStore` method for document-scoped deletion (for example `delete_document(namespace, document_id)`), implemented in `app/providers/vector_stores/pgvector.py`.
  - [x] Use a parameterized SQL delete with both namespace and document ID filters.
  - [x] Keep `VectorStore` interface method signatures unchanged (`upsert`, `query`, `delete_namespace`, `health` remain intact).
  - [x] If provider capability is absent for configured vector store, fail with `ProviderUnavailableError` instead of silently skipping vector cleanup.

- [x] Implement metadata record cleanup and return semantics (AC: 1)
  - [x] Delete `ingestion_jobs` rows associated with the document using DAO methods.
  - [x] Delete the `documents` record after vector cleanup succeeds.
  - [x] Optionally delete archived S3 object by `s3_key` if present; if this is implemented, keep behavior deterministic and test-covered.
  - [x] Return no body on success (`204 No Content`).

- [x] Preserve failure safety and anti-regression behavior (AC: 1, 2, 3)
  - [x] Do not perform partial destructive writes before ownership checks complete.
  - [x] Keep vector deletion first in the destructive sequence so namespace cleanup failure does not remove Mongo records prematurely.
  - [x] Log operation context (`tenant_id`, `agent_id`, `document_id`) without logging raw document or chunk content.
  - [x] Do not add DynamoDB job tracking back into deletion flow (legacy architecture removed it in Story 1.10).

- [x] Add focused tests for route, service, and provider behavior (AC: 1, 2, 3)
  - [x] Extend `tests/api/v1/test_documents_dao.py` with `DELETE` route coverage for 204/403/404 and service-call delegation.
  - [x] Extend `tests/services/test_ingestion_service_dao.py` with ownership checks, not-found behavior, and successful cleanup orchestration.
  - [x] Extend `tests/providers/vector_stores/test_pgvector.py` with document-scoped delete SQL assertions (`WHERE namespace = $1 AND document_id = $2`).
  - [x] Add/adjust tests to ensure no DynamoDB client calls are introduced for document deletion.

### Review Findings

- [x] [Review][Patch] Tenant-safe metadata cleanup uses `document_id` alone and can over-delete records if IDs ever collide or data is corrupted [`app/services/ingestion_service.py:314`]

## Dev Notes

### Story Intent and Scope

- This story introduces per-document cleanup for vectors plus metadata records.
- The core risk is cross-tenant deletion; ownership checks must happen before destructive calls.
- This story should not change ingestion status architecture; status tracking is MongoDB-backed (`ingestion_jobs`) in current codebase.

### Architecture Guardrails (Must Follow)

- Namespace isolation is zero-tolerance; namespace must always be derived as `{tenant_id}_{agent_id}`.  
  [Source: `_bmad-output/planning-artifacts/architecture.md`]
- Provider resolution must go through registry/dependencies (`get_vector_store`) and not direct instantiation in services.  
  [Source: `_bmad-output/planning-artifacts/architecture.md`]
- Raw pgvector access belongs only in provider module (`app/providers/vector_stores/pgvector.py`), not in service code.  
  [Source: `_bmad-output/planning-artifacts/architecture.md`]
- Typed errors from `app/core/errors.py` should drive HTTP mapping (`DocumentNotFoundError`, `ForbiddenError`, `ProviderUnavailableError`).  
  [Source: `app/core/errors.py`]

### Codebase Reality and Required Touchpoints

- Document routes currently provide upload/status/list only; delete endpoint is not implemented yet.  
  [Source: `app/api/v1/documents.py`]
- Existing service has upload/status/list functions and already uses `document_dao` + `ingestion_job_dao`.  
  [Source: `app/services/ingestion_service.py`]
- Agent deletion already demonstrates cleanup ordering and vector store invocation patterns; reuse this style for document-level cleanup.  
  [Source: `app/services/agent_service.py`]
- Current `PgVectorStore` supports namespace deletion but not document-scoped deletion; this story fills that gap.  
  [Source: `app/providers/vector_stores/pgvector.py`]

### Implementation Pattern Recommendation

1. Validate agent exists and tenant owns it (`agent_service.get_agent`).
2. Load document by `document_id`; fail 404 if absent, 403 if tenant/agent mismatch.
3. Resolve vector store from agent config.
4. Perform namespace+document scoped vector deletion in provider.
5. Delete ingestion job record(s) for the document.
6. Delete document record.
7. Return 204.

This sequence minimizes inconsistent state for the highest-risk boundary (namespace-isolated vector data).

### Previous Story Intelligence (4.3)

- Story 4.3 established pgvector provider and strict namespace filtering in `query`.
- Provider errors are wrapped as `ProviderUnavailableError`.
- Registry-driven provider resolution is already in place and should be reused directly.
- Do not leak chunk text or embeddings in logs.

[Source: `_bmad-output/implementation-artifacts/4-3-pgvector-upsert-with-namespace-isolation.md`]

### Git Intelligence (Recent Patterns)

- DAO-first access pattern and removal of ingestion DynamoDB dependency are already established in recent commits.
- Ingestion flow work has used strict service-layer orchestration plus thin routes.

[Source: `git log --oneline -n 20`]

### Latest Technical Information (Verified on 2026-05-01)

- `pgvector` PyPI latest version is `0.4.2` (released 2025-12-05); project requires Python >=3.9.
- `asyncpg` PyPI latest version is `0.31.0` (released 2025-11-24).
- pgvector Python asyncpg guidance explicitly shows registering vector types at pool init (`asyncpg.create_pool(..., init=init)` with `register_vector(conn)`), which aligns with current provider bootstrapping strategy.
- PostgreSQL `DELETE ... RETURNING` can be used to capture deleted-row metadata if implementation needs confirmation/logging without extra round-trips.
- FastAPI `204 No Content` responses must not return a response body.

[Source: https://pypi.org/project/pgvector/]  
[Source: https://pypi.org/project/asyncpg/]  
[Source: https://github.com/pgvector/pgvector-python]  
[Source: https://www.postgresql.org/docs/current/dml-returning.html]  
[Source: https://fastapi.tiangolo.com/tutorial/response-status-code/]

### Project Structure Notes

- Keep changes contained to existing layers and paths:
  - `app/api/v1/documents.py`
  - `app/services/ingestion_service.py`
  - `app/providers/vector_stores/pgvector.py`
  - `tests/api/v1/test_documents_dao.py`
  - `tests/services/test_ingestion_service_dao.py`
  - `tests/providers/vector_stores/test_pgvector.py`

- Avoid introducing new architecture seams unless unavoidable; this story is an extension of current delete flows, not a redesign.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 4.4`]
- [Source: `_bmad-output/planning-artifacts/architecture.md`]
- [Source: `_bmad-output/planning-artifacts/prd.md`]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-04-30.md`]
- [Source: `_bmad-output/project-context.md`]
- [Source: `app/api/v1/documents.py`]
- [Source: `app/services/ingestion_service.py`]
- [Source: `app/services/agent_service.py`]
- [Source: `app/providers/vector_stores/pgvector.py`]
- [Source: `app/interfaces/vector_store.py`]
- [Source: `app/core/errors.py`]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- 2026-05-01: Story context creation (`bmad-create-story`)
- 2026-05-02: Implemented `DELETE /v1/agents/{agent_id}/documents/{document_id}` route and service orchestration.
- 2026-05-02: Added pgvector document-scoped deletion and comprehensive route/service/provider tests.
- 2026-05-02: Executed full regression suite (`188 passed, 9 skipped`).

### Completion Notes List

- Added `DELETE /v1/agents/{agent_id}/documents/{document_id}` route with thin-router delegation and 204 semantics.
- Implemented `ingestion_service.delete_document` with strict ownership checks, namespace derivation, and ordered cleanup (vectors first, then `ingestion_jobs`, then `documents`).
- Added `PgVectorStore.delete_document(namespace, document_id)` using parameterized SQL with namespace + document filters.
- Added provider-capability guard that raises `ProviderUnavailableError` when document-scoped delete is not supported.
- Extended tests for route outcomes (204/403/404), service not-found/forbidden/orchestration paths, and provider SQL assertion.
- Ran full test suite successfully: `188 passed, 9 skipped`.

### File List

- _bmad-output/implementation-artifacts/4-4-document-deletion-with-chunk-cleanup.md
- app/api/v1/documents.py
- app/services/ingestion_service.py
- app/providers/vector_stores/pgvector.py
- tests/api/v1/test_documents_dao.py
- tests/services/test_ingestion_service_dao.py
- tests/providers/vector_stores/test_pgvector.py
- tests/core/test_dependencies.py

## Change Log

- 2026-05-02: Implemented document deletion route/service/provider flow and added route/service/provider test coverage.
- 2026-05-02: Corrected dependency unknown-provider tests to use truly unknown keys during full-suite regression validation.

## Completion Note

Ultimate context engine analysis completed - comprehensive developer guide created.
