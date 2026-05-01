# Story 4.3: pgvector Upsert with Namespace Isolation

Status: done

## Story

As a Tenant Developer,
I want embedded chunks stored in pgvector under a strictly isolated namespace per agent,
so that no agent's retrieval can ever access another agent's documents.

## Acceptance Criteria

**AC1:** Given an agent configured with `vector_store: pgvector`, when `PgVectorStore.upsert(namespace, vectors)` is called after embedding, then all vectors are inserted into the pgvector-backed document chunks table under namespace `{tenant_id}_{agent_id}`; the namespace is derived from the agent config and payload, never hardcoded inline.

**AC2:** Given the ingestion worker successfully completes parse, PII scrub, chunking, embedding, and vector upsert, when `run_ingestion_pipeline()` returns, then the existing worker status flow updates the MongoDB `ingestion_jobs` and `documents` records to `DocumentStatus.ready`. Do not reintroduce DynamoDB job status.

**AC3:** Given a `PgVectorStore.query(namespace, vector, top_k, filters)` call, when it executes, then the namespace is applied as a hard SQL filter on every query before ordering or limiting results; namespace is not optional and cannot be weakened by metadata filters.

**AC4:** Given a query result row has a namespace different from the requested namespace, when `PgVectorStore.query()` validates results, then `NamespaceViolationError` is raised immediately, the offending result is not returned, and a critical/error log includes `tenant_id`, `agent_id`, and the requested namespace without logging chunk text.

**AC5:** Given the pipeline needs a vector store for an agent, when the store is resolved, then it uses `VECTOR_STORE_REGISTRY["pgvector"]` / `get_vector_store(agent.vector_store)` patterns and never directly instantiates `PgVectorStore` inside ingestion or service logic.

## Tasks / Subtasks

- [x] Add the pgvector provider implementation (AC: 1, 3, 4)
  - [x] Create `app/providers/vector_stores/pgvector.py`.
  - [x] Implement the locked `VectorStore` interface from `app/interfaces/vector_store.py`: `upsert`, `query`, `delete_namespace`, and `health`.
  - [x] Add `PgVectorStore` to `VECTOR_STORE_REGISTRY` in `app/providers/registry.py`.
  - [x] Add required dependency support for pgvector Python integration if needed by the implementation.

- [x] Define the storage contract and namespace behavior (AC: 1, 3, 4)
  - [x] Store one row per `VectorRecord` with at least `id`, `namespace`, `vector`, `metadata`, `text`, `document_id`, `chunk_index`, and timestamps.
  - [x] Use namespace value exactly as `f"{tenant_id}_{agent_id}"`; do not derive a different format.
  - [x] Use SQL parameters for all values; do not interpolate namespace, vector payloads, filters, or IDs into SQL strings.
  - [x] Preserve `ChunkMetadata` so later retrieval can return citations and apply metadata filters.

- [x] Replace the ingestion upsert stub (AC: 1, 2, 5)
  - [x] Replace `_upsert_to_vector_store_stub()` in `app/pipelines/ingestion/pipeline.py` with a real upsert step.
  - [x] Convert embedded `Chunk` objects into `VectorRecord` objects; fail fast if any chunk is missing `vector`.
  - [x] Resolve the store through `get_vector_store(agent.vector_store)` or `VECTOR_STORE_REGISTRY`, consistent with current provider patterns.
  - [x] Keep status updates in `app/workers/ingestion_worker.py`; successful upsert should make `run_ingestion_pipeline()` return, allowing the worker to mark MongoDB job/document records ready.

- [x] Add query and delete behavior needed by later stories (AC: 3, 4)
  - [x] Implement `query()` with namespace hard filter plus optional metadata filters.
  - [x] Validate every returned row's namespace before constructing `VectorResult`.
  - [x] Implement `delete_namespace(namespace)` for existing agent deletion flow in `app/services/agent_service.py`.
  - [x] Implement `health()` for readiness checks and future observability.

- [x] Add focused tests (AC: 1-5)
  - [x] Create `tests/providers/vector_stores/test_pgvector.py`.
  - [x] Test `upsert()` persists namespace and metadata for multiple vectors.
  - [x] Test `query()` always includes namespace as a hard filter and metadata filters cannot override it.
  - [x] Test cross-namespace result validation raises `NamespaceViolationError`.
  - [x] Test `delete_namespace()` only deletes rows in the requested namespace.
  - [x] Update `tests/providers/test_registry.py` to expect `"pgvector"` in `VECTOR_STORE_REGISTRY` and preserve existing registered providers.
  - [x] Update `tests/pipelines/ingestion/test_pipeline.py` to assert the pipeline calls vector store upsert after embeddings and no longer patches `_upsert_to_vector_store_stub`.

## Dev Notes

### Relevant Architecture

- pgvector is the MVP vector store for Stage 4 and must live under `app/providers/vector_stores/pgvector.py`. [Source: `_bmad-output/planning-artifacts/architecture.md`]
- `VectorStore` method names and signatures are locked in `app/interfaces/vector_store.py`; do not rename or widen the interface for this story. [Source: `app/interfaces/vector_store.py`]
- Namespace isolation is a zero-tolerance cross-cutting concern enforced at vector-store level, not at application layer. [Source: `_bmad-output/planning-artifacts/architecture.md#Cross-Cutting Concerns Identified`]
- The namespace format is exactly `{tenant_id}_{agent_id}`. Both IDs are MongoDB ObjectIds and the resulting string is safe for pgvector/Qdrant/Pinecone namespace concepts. [Source: `_bmad-output/planning-artifacts/architecture.md#D8`]
- All pluggable providers are registered in `app/providers/registry.py`; new providers are added there and resolved through registry/dependency helpers. [Source: `_bmad-output/planning-artifacts/architecture.md#Provider Registration`]
- MongoDB collection access goes through `app/db/` DAOs. Do not use raw Motor collections from services, pipeline, or providers. [Source: `_bmad-output/planning-artifacts/architecture.md#DAO Layer`]

### Current Codebase State

- `app/pipelines/ingestion/pipeline.py` already performs S3 download, parsing, PII scrubbing, chunking through `CHUNKING_REGISTRY`, embedding through `EMBEDDING_REGISTRY`, then calls `_upsert_to_vector_store_stub()`.
- `Chunk.vector` is populated by `_generate_embeddings()` and `VectorRecord` already exists in `app/models/chunk.py`.
- `app/workers/ingestion_worker.py` is the current status owner: it marks `DocumentStatus.processing` before the pipeline and marks both `ingestion_jobs` and `documents` ready after `run_ingestion_pipeline()` returns.
- `app/services/agent_service.py` already calls `get_vector_store(doc.vector_store).delete_namespace(namespace)` during agent deletion, so `PgVectorStore.delete_namespace()` must work in this story.
- `app/core/dependencies.py:get_vector_store()` currently instantiates registered stores with no constructor arguments. If `PgVectorStore` needs settings or connection details, keep the public dependency simple by reading `get_settings()`/Secrets Manager inside the provider or by making constructor defaults compatible with `get_vector_store()`.

### Data Model Guidance

- Prefer one document vector table, for example `document_vectors`, with a `namespace` text column and a pgvector `embedding` column. Do not create one table per tenant or one schema per agent.
- Store metadata as structured JSON/JSONB and also promote fields used for filters/deletes (`namespace`, `tenant_id`, `agent_id`, `document_id`, `chunk_index`) into queryable columns if that keeps SQL simple and testable.
- Use deterministic vector IDs already implied by `VectorRecord.id`, such as `{document_id}_{chunk_index}`. Upsert should be idempotent for the same namespace and vector ID.
- Use cosine distance unless the implementation has a documented project reason to choose another distance operator.
- Do not log `VectorRecord.text`, chunk text, raw document content, vectors, or query text.

### Error Handling

- Use `NamespaceViolationError` from `app/core/errors.py` for cross-namespace rows.
- Use `ProviderUnavailableError` for pgvector connection/query failures that make the provider unavailable.
- Let worker-level failure handling mark MongoDB job/document records failed when upsert raises.
- Keep critical namespace-violation logs structured and content-safe: include IDs, namespace, operation, and provider; exclude document text.

### Testing Standards

- Tests live under `tests/` mirroring `app/` paths. [Source: `_bmad-output/planning-artifacts/architecture.md#Test Location`]
- Unit tests can mock the async database connection/pool; integration tests with a real PostgreSQL/pgvector instance are useful but should not be required for the normal unit test suite unless the repo already provides that fixture.
- Add regression coverage that metadata filters cannot override namespace. This is the highest-risk behavior in the story.
- Update existing tests that still assume empty provider registries; Story 4.2 already registered OpenAI and Story 4.3 must register pgvector.

### Previous Story Intelligence

- Story 4.2 implemented OpenAI embeddings and renamed the remaining ingestion tail to `_upsert_to_vector_store_stub()`.
- Existing pipeline pattern resolves providers by registry key and raises if a configured provider is not registered.
- The previous story added `openai>=1.0.0` to `requirements.txt` but `pyproject.toml` currently only lists `beanie`; check dependency management before adding pgvector packages.
- Recent commits show the current path: chunking provider, embedding provider, then vector upsert. Continue that pattern instead of introducing a separate ingestion abstraction.

### Latest Technical Information

- pgvector's Python package provides asyncpg integration via `pgvector.asyncpg.register_vector`, which should be registered on connections before using vector values. Source: https://github.com/pgvector/pgvector-python
- pgvector supports HNSW and IVFFlat indexes. This story can start with correct storage/query semantics first; index tuning can be added later if not needed for unit-testable MVP behavior. Source: https://github.com/pgvector/pgvector
- SQLAlchemy asyncio with asyncpg is already allowed by architecture, but the current `VectorStore` provider can use direct `asyncpg` if that keeps implementation smaller and consistent with the architecture's pgvector note. Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html

### Project Structure Notes

- Create: `app/providers/vector_stores/pgvector.py`
- Update: `app/providers/vector_stores/__init__.py` only if needed for imports
- Update: `app/providers/registry.py`
- Update: `app/pipelines/ingestion/pipeline.py`
- Update: `requirements.txt` and/or `pyproject.toml` if a new pgvector Python dependency is required
- Add: `tests/providers/vector_stores/test_pgvector.py`
- Update: `tests/providers/test_registry.py`
- Update: `tests/pipelines/ingestion/test_pipeline.py`

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 4.3`]
- [Source: `_bmad-output/planning-artifacts/architecture.md#D8`]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-04-30.md`]
- [Source: `_bmad-output/project-context.md`]
- [Source: `app/interfaces/vector_store.py`]
- [Source: `app/models/chunk.py`]
- [Source: `app/pipelines/ingestion/pipeline.py`]
- [Source: `app/workers/ingestion_worker.py`]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- 2026-05-01: `.venv/bin/python -m pytest tests/providers/test_registry.py tests/pipelines/ingestion/test_pipeline.py tests/providers/vector_stores/test_pgvector.py` (19 passed)
### Completion Notes List

- Implemented `PgVectorStore` with `upsert`, `query`, `delete_namespace`, and `health`, using parameterized SQL and namespace hard filtering.
- Replaced ingestion vector-store stub with real provider resolution via `get_vector_store(agent.vector_store)` and `VectorRecord` conversion.
- Added fast-fail behavior when chunks are missing vectors before upsert.
- Added namespace violation validation and structured error logging without chunk text exposure.
- Added focused pgvector unit tests and updated registry + ingestion pipeline tests.
### File List

- app/providers/vector_stores/pgvector.py
- app/providers/registry.py
- app/pipelines/ingestion/pipeline.py
- requirements.txt
- tests/providers/vector_stores/test_pgvector.py
- tests/providers/test_registry.py
- tests/pipelines/ingestion/test_pipeline.py
## Completion Note

Ultimate context engine analysis completed - comprehensive developer guide created.
