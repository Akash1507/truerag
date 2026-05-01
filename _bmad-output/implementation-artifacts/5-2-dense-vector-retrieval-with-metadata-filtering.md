# Story 5.2: Dense Vector Retrieval with Metadata Filtering

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a Service Consumer,
I want my query to retrieve the most relevant chunks from the agent's pgvector namespace using dense similarity search, with optional metadata filters,
so that retrieval is scoped precisely to the relevant documents and namespace (FR28, FR29).

## Acceptance Criteria

1. `PgVectorStore.query(namespace, vector, top_k, filters)` is called with namespace `{tenant_id}_{agent_id}` as a hard filter on every query — regardless of any other parameter.
2. Top-k most similar chunks are returned from the agent's namespace only; no cross-namespace result is ever returned.
3. Optional metadata filters (e.g. `{"document_id": "..."}`) are accepted via `QueryRequest.filters`; when provided, only chunks matching both the namespace filter and the metadata filter are returned.
4. Every returned chunk carries full metadata: `tenant_id`, `agent_id`, `document_id`, `chunk_index`, `chunking_strategy`, `version`.
5. `QueryResponse.citations` is populated from the retrieved `VectorResult` list; `answer` remains `""` and `confidence` remains `0.0` (wired in Story 5.3); `latency_ms` is measured end-to-end by `run_query_pipeline` (unchanged).
6. Embedding of the scrubbed query text uses the agent's configured `embedding_provider` resolved from `EMBEDDING_REGISTRY`.
7. Vector store used for retrieval is resolved from `VECTOR_STORE_REGISTRY` using `agent.vector_store`.
8. `ProviderUnavailableError` from the embedder or vector store propagates unmodified (FastAPI handler → HTTP 503).
9. `NamespaceViolationError` raised by `PgVectorStore` propagates unmodified (hard security error).
10. Structured log entries are emitted for `embedding_complete` and `retrieval_complete` operations, matching existing pipeline observability pattern.

## Tasks / Subtasks

- [x] Task 1: Add `filters` field to `QueryRequest` model (AC: 3)
  - [x] 1.1 In `app/models/query.py`, add `filters: dict[str, str] | None = None` to `QueryRequest` after `top_k`
  - [x] 1.2 No change to `QueryResponse` or `Citation` — these shapes are already correct for this story

- [x] Task 2: Thread `filters` through `query_service` and `run_query_pipeline` (AC: 1, 3)
  - [x] 2.1 In `app/services/query_service.py`, update the `run_query_pipeline` call to pass `filters=request.filters`
  - [x] 2.2 In `app/pipelines/query/pipeline.py`, add `filters: dict[str, str] | None = None` parameter to `run_query_pipeline` signature
  - [x] 2.3 Pass `filters` through to `_execute_retrieval` (see Task 3)

- [x] Task 3: Replace `_execute_stub` with `_execute_retrieval` in query pipeline (AC: 1, 2, 4, 5, 6, 7, 8, 9, 10)
  - [x] 3.1 Delete `_execute_stub` entirely from `app/pipelines/query/pipeline.py`
  - [x] 3.2 Add imports: `from app.providers.registry import EMBEDDING_REGISTRY, VECTOR_STORE_REGISTRY` and `from app.core.errors import ProviderUnavailableError` and `from app.models.query import Citation`
  - [x] 3.3 Implement `async def _execute_retrieval(scrubbed_query: str, top_k: int, agent: AgentDocument, filters: dict[str, str] | None) -> QueryResponse`:
    - Resolve embedder: `embedder_cls = EMBEDDING_REGISTRY.get(agent.embedding_provider)` — if `None`, raise `ProviderUnavailableError(f"Embedding provider '{agent.embedding_provider}' not registered")`
    - Instantiate: `embedder = embedder_cls()` (no `aws_session` arg for query path — matches ingestion pattern where worker passes session; query handler has no session)
    - Embed: `vectors = await embedder.embed([scrubbed_query])` → `query_vector = vectors[0]`
    - Log `embedding_complete` (see Dev Notes for exact pattern)
    - Resolve vector store: `vs_cls = VECTOR_STORE_REGISTRY.get(agent.vector_store)` — if `None`, raise `ProviderUnavailableError(f"Vector store '{agent.vector_store}' not registered")`
    - Instantiate: `vs = vs_cls()`
    - Build namespace: `namespace = f"{agent.tenant_id}_{agent.agent_id}"`
    - Query: `results = await vs.query(namespace, query_vector, top_k, filters)`
    - Log `retrieval_complete` (see Dev Notes for exact pattern)
    - Map to citations: `citations = [Citation(document_name=r.metadata.document_id, chunk_text=r.text, page_reference=None) for r in results]`
    - Return `QueryResponse(answer="", confidence=0.0, citations=citations, latency_ms=0)` — `latency_ms` is overwritten by `run_query_pipeline`; set to `0` here
  - [x] 3.4 Update the call site in `run_query_pipeline`: replace `await _execute_stub(...)` with `await _execute_retrieval(scrubbed_query=scrubbed_query, top_k=top_k, agent=agent, filters=filters)`

- [x] Task 4: Update existing pipeline tests (AC: 1, 5, 6, 7)
  - [x] 4.1 In `tests/pipelines/test_query_pipeline.py`, replace all patches of `app.pipelines.query.pipeline._execute_stub` with `app.pipelines.query.pipeline._execute_retrieval` — the existing integration-level assertions (scrub called before downstream, call order) still apply; only the patch target changes
  - [x] 4.2 Add new test: `test_pipeline_embeds_and_queries_vector_store` — mock `EMBEDDING_REGISTRY`, `VECTOR_STORE_REGISTRY`, assert embedder called with `[scrubbed_query]`, vector store called with correct namespace and `top_k`
  - [x] 4.3 Add new test: `test_pipeline_maps_results_to_citations` — mock vector store returning two `VectorResult` objects; assert `QueryResponse.citations` has two `Citation` entries with correct `document_name` (= `document_id`), `chunk_text`, `page_reference=None`
  - [x] 4.4 Add new test: `test_pipeline_passes_filters_to_vector_store` — call `run_query_pipeline` with `filters={"document_id": "doc-1"}`; assert vector store `query` called with `filters={"document_id": "doc-1"}`
  - [x] 4.5 Add new test: `test_pipeline_unregistered_embedding_provider_raises_503` — set `agent.embedding_provider = "unknown"`; assert `ProviderUnavailableError` raised
  - [x] 4.6 Add new test: `test_pipeline_unregistered_vector_store_raises_503` — set `agent.vector_store = "unknown"`; assert `ProviderUnavailableError` raised
  - [x] 4.7 Add new test: `test_pipeline_no_filters_passes_none_to_vector_store` — call with no `filters`; assert vector store `query` called with `filters=None`

- [x] Task 5: Update query service tests (AC: 3)
  - [x] 5.1 In `tests/services/test_query_service.py`, update `QueryRequest` fixtures to optionally include `filters={"document_id": "doc-1"}`
  - [x] 5.2 Add test: `test_handle_query_passes_filters_to_pipeline` — `request.filters = {"document_id": "doc-1"}`; assert `run_query_pipeline` called with `filters={"document_id": "doc-1"}`
  - [x] 5.3 Add test: `test_handle_query_passes_none_filters_when_omitted` — `request.filters = None`; assert `run_query_pipeline` called with `filters=None`

- [x] Task 6: Update route-layer tests (AC: 3)
  - [x] 6.1 In `tests/api/v1/test_query.py`, add test: POST `{"query": "...", "filters": {"document_id": "doc-1"}}` → assert HTTP 200 and filters propagated
  - [x] 6.2 Add test: POST without `filters` key → assert HTTP 200 (field is optional, defaults to `None`)

## Dev Notes

### Architecture Guardrails (Must Follow)

**Namespace isolation is ZERO-TOLERANCE** [Source: architecture.md#Critical Invariants]:
- Namespace format: `f"{agent.tenant_id}_{agent.agent_id}"` — exact same format as ingestion pipeline (line 143 of `app/pipelines/ingestion/pipeline.py`)
- Never derive namespace from user input — always derive from the authenticated `AgentDocument`
- `PgVectorStore.query` already enforces namespace at the DB level AND double-checks returned rows — `NamespaceViolationError` means a DB-level bug occurred; it must propagate, never be caught and suppressed

**Registry lookup pattern** — match ingestion pipeline exactly [Source: `app/pipelines/ingestion/pipeline.py` lines 108-111]:
```python
embedder_cls = EMBEDDING_REGISTRY.get(agent.embedding_provider)
if not embedder_cls:
    raise ProviderUnavailableError(f"Embedding provider '{agent.embedding_provider}' not registered")
embedder = embedder_cls()
```
Do NOT use `embedder_cls(aws_session=aws_session)` in the query path — there is no `aws_session` in the query pipeline (no SQS worker context). The OpenAI embedder's `__init__` accepts `aws_session: aioboto3.Session | None = None` with default `None`, so `embedder_cls()` is correct.

**`retrieval_mode` guard**: This story only handles `dense`. The epic's `retrieval_mode` field on `AgentDocument` has values `{"dense", "sparse", "hybrid"}`. For MVP, all agents will be configured `dense`. Do NOT add a guard that raises on non-dense mode — Story 7.2 adds sparse/hybrid. Leave it implicit: this pipeline always does dense regardless of `retrieval_mode` until Epic 7.

**`_execute_stub` deletion**: The existing tests in `test_query_pipeline.py` patch `_execute_stub`. When you delete it and replace with `_execute_retrieval`, those patches break. You MUST update them in Task 4.1 or the test suite will error (not just fail).

**Do not change `run_query_pipeline`'s latency measurement**: `t0 = time.perf_counter()` and `latency_ms` computation already wrap the entire pipeline. Return `latency_ms=0` inside `_execute_retrieval` — it gets overwritten by `run_query_pipeline`.

### Observability Pattern (exact structure required)

Embedding log — match ingestion pattern [Source: `app/pipelines/ingestion/pipeline.py` lines 126-133]:
```python
logger.info(
    "embedding_complete",
    extra={
        "operation": "embedding",
        "extra_data": {
            "tenant_id": agent.tenant_id,
            "agent_id": agent.agent_id,
            "provider": agent.embedding_provider,
        },
    },
)
```

Retrieval log — match ingestion pattern [Source: `app/pipelines/ingestion/pipeline.py` lines 162-171]:
```python
logger.info(
    "retrieval_complete",
    extra={
        "operation": "retrieval",
        "extra_data": {
            "tenant_id": agent.tenant_id,
            "agent_id": agent.agent_id,
            "chunk_count": len(results),
            "provider": agent.vector_store,
        },
    },
)
```

### Citation Mapping

`VectorResult` → `Citation` mapping for this story:
- `Citation.document_name` = `result.metadata.document_id` (document name lookup added later when document model is extended)
- `Citation.chunk_text` = `result.text`
- `Citation.page_reference` = `None` (no page tracking in MVP chunking)

`QueryResponse.answer = ""` and `confidence = 0.0` remain stubs until Story 5.3 wires LLM generation.

### `PgVectorStore.query` — exact signature and behavior

Already fully implemented at `app/providers/vector_stores/pgvector.py`:
```python
async def query(
    self, namespace: str, vector: list[float], top_k: int, filters: dict[str, str] | None
) -> list[VectorResult]:
```
- Filters applied as `metadata ->> $key = $value` JSONB lookups (string equality only)
- Result rows validated for namespace match — raises `NamespaceViolationError` on mismatch
- Returns `list[VectorResult]` where each `VectorResult.score = 1.0 - distance` (cosine similarity, higher = more similar)

### Test Mock Pattern for Registry

For pipeline tests, mock the registries directly:
```python
from unittest.mock import AsyncMock, MagicMock, patch
from app.models.chunk import ChunkMetadata, VectorResult
from datetime import datetime, timezone

def _make_vector_result(document_id: str = "doc-1", chunk_index: int = 0) -> VectorResult:
    return VectorResult(
        id=f"{document_id}_{chunk_index}",
        score=0.92,
        metadata=ChunkMetadata(
            tenant_id="tenant-1",
            agent_id="agent-1",
            document_id=document_id,
            chunk_index=chunk_index,
            chunking_strategy="fixed_size",
            timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
            version=1,
        ),
        text="relevant chunk text",
    )

# In test:
mock_embedder = AsyncMock()
mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
mock_embedder_cls = MagicMock(return_value=mock_embedder)

mock_vs = AsyncMock()
mock_vs.query = AsyncMock(return_value=[_make_vector_result()])
mock_vs_cls = MagicMock(return_value=mock_vs)

with (
    patch("app.pipelines.query.pipeline.EMBEDDING_REGISTRY", {"openai": mock_embedder_cls}),
    patch("app.pipelines.query.pipeline.VECTOR_STORE_REGISTRY", {"pgvector": mock_vs_cls}),
):
    result = await run_query_pipeline("my query", 5, agent)
```

Note: `mock_embedder_cls` is a `MagicMock` (not `AsyncMock`) because it's instantiated with `()`, not awaited.

### Conftest Fixtures

- `mock_beanie_collection_access` — required for all tests that instantiate `AgentDocument` (Beanie ODM requires collection init)
- `_make_agent()` helper already exists in `tests/pipelines/test_query_pipeline.py` — reuse it
- `client` fixture for route-layer tests — already set up in conftest

### Project Structure Notes

Files modified by this story:
- `app/models/query.py` — add `filters` field to `QueryRequest`
- `app/services/query_service.py` — pass `filters=request.filters` to `run_query_pipeline`
- `app/pipelines/query/pipeline.py` — add `filters` param to `run_query_pipeline`; delete `_execute_stub`; add `_execute_retrieval`; add imports

Files with tests that MUST be updated (not just added to):
- `tests/pipelines/test_query_pipeline.py` — update `_execute_stub` patches to `_execute_retrieval`

Files with tests that get new test cases:
- `tests/pipelines/test_query_pipeline.py` — new retrieval/citation/filter tests
- `tests/services/test_query_service.py` — filters threading tests
- `tests/api/v1/test_query.py` — filters in request body tests

Files NOT touched by this story:
- `app/providers/vector_stores/pgvector.py` — already fully implemented
- `app/providers/embedding/openai.py` — already fully implemented
- `app/providers/registry.py` — no changes needed
- `app/api/v1/query.py` — route delegates to service; no change needed
- `app/interfaces/` — abstract interfaces unchanged
- `tests/providers/vector_stores/test_pgvector.py` — pgvector unit tests unchanged

### References

- [Source: epics.md#Epic 5 Story 5.2] — acceptance criteria and user story
- [Source: architecture.md#Critical Invariants] — namespace isolation zero-tolerance, NFR9, NFR10
- [Source: app/providers/vector_stores/pgvector.py] — `PgVectorStore.query` exact signature and behavior
- [Source: app/interfaces/vector_store.py] — `VectorStore` abstract interface
- [Source: app/interfaces/embedding_provider.py] — `EmbeddingProvider.embed(texts: list[str]) -> list[list[float]]`
- [Source: app/providers/embedding/openai.py] — `OpenAIEmbedder.embed` implementation; model = `text-embedding-3-small`
- [Source: app/providers/registry.py] — `EMBEDDING_REGISTRY`, `VECTOR_STORE_REGISTRY` dicts
- [Source: app/pipelines/ingestion/pipeline.py#_generate_embeddings] — registry lookup pattern (lines 108-111, 143)
- [Source: app/models/chunk.py] — `VectorResult`, `ChunkMetadata` field shapes
- [Source: app/models/query.py] — `QueryRequest`, `QueryResponse`, `Citation` current shapes
- [Source: app/pipelines/query/pipeline.py] — current `run_query_pipeline` + `_execute_stub` implementation
- [Source: app/services/query_service.py] — `handle_query` current implementation
- [Source: app/core/errors.py] — `ProviderUnavailableError`, `NamespaceViolationError`
- [Source: tests/pipelines/test_query_pipeline.py] — `_make_agent()` helper and existing test patterns
- [Source: tests/providers/vector_stores/test_pgvector.py] — asyncpg mock pattern (`store._get_pool = AsyncMock(return_value=pool)`)

## Dev Agent Record

### Agent Model Used

gpt-5

### Debug Log References

- Targeted tests: `.venv/bin/python -m pytest tests/pipelines/test_query_pipeline.py tests/services/test_query_service.py tests/api/v1/test_query.py`
- Full regression: `.venv/bin/python -m pytest`

### Completion Notes List

- Added optional `filters` to `QueryRequest` and threaded it through query service to `run_query_pipeline`.
- Replaced `_execute_stub` with dense retrieval via embedding and vector-store registries, enforced namespace query construction from `AgentDocument`, and mapped `VectorResult` objects to `Citation`.
- Added structured `embedding_complete` and `retrieval_complete` logs in the query pipeline.
- Preserved existing latency measurement behavior in `run_query_pipeline` with retrieval returning `latency_ms=0` for overwrite.
- Added pipeline, service, and route tests covering filter propagation, citation mapping, registry resolution, and provider-unavailable error propagation.
- Verified regressions with full suite: `225 passed, 9 skipped`.

### File List

### Review Findings

- [x] [Review][Patch] Empty embedding result crashes the query pipeline instead of returning a controlled provider failure [app/pipelines/query/pipeline.py:48]
- [x] [Review][Patch] Story AC9 and AC10 are not pinned by tests; the new suite does not cover `NamespaceViolationError` pass-through or `embedding_complete` / `retrieval_complete` log emission [tests/pipelines/test_query_pipeline.py:105]

- app/models/query.py
- app/services/query_service.py
- app/pipelines/query/pipeline.py
- tests/pipelines/test_query_pipeline.py
- tests/services/test_query_service.py
- tests/api/v1/test_query.py

### Change Log

- 2026-05-02: Implemented Story 5.2 dense retrieval with metadata filters and moved status to review after full regression pass.
