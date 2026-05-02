# Story 8.1: Qdrant Vector Store Backend

Status: done

## Story

As a Tenant Developer,
I want to configure my agent to use Qdrant Cloud as its vector store backend,
so that I can choose a purpose-built vector database for higher throughput workloads (FR23).

## Acceptance Criteria

**AC1 — Qdrant upsert stores vectors in namespace-scoped collection**
Given an agent configured with `vector_store: qdrant`
When `QdrantVectorStore.upsert(namespace, vectors)` is called
Then vectors are stored in a Qdrant Cloud collection scoped to namespace `{tenant_id}_{agent_id}`; the Qdrant API key is read from AWS Secrets Manager via `secrets.py`

**AC2 — Qdrant query enforces namespace isolation**
Given `QdrantVectorStore.query(namespace, vector, top_k, filters)`
When called
Then namespace is applied as a hard filter; cross-namespace results are never returned; `NamespaceViolationError` is raised if a cross-namespace result is detected

**AC3 — Registered in VECTOR_STORE_REGISTRY and passes backend-agnostic contract tests**
Given `QdrantVectorStore` registered in `VECTOR_STORE_REGISTRY["qdrant"]`
When the backend-agnostic vector store test suite runs against it
Then all assertions pass — the same test suite that validates `PgVectorStore` validates `QdrantVectorStore` with only the backend swapped

## Tasks / Subtasks

- [x] **Task 1: Add Qdrant config to `app/core/config.py`** (AC: 1)
  - [x] Add `qdrant_api_key_secret_name: str = "truerag/qdrant/api_key"` to `Settings`
  - [x] Add `qdrant_url: str = "https://your-cluster.qdrant.io"` to `Settings` (populated via env var `QDRANT_URL`)

- [x] **Task 2: Implement `app/providers/vector_stores/qdrant.py`** (AC: 1, 2)
  - [x] Class `QdrantVectorStore(VectorStore)` — implements full abstract interface
  - [x] `__init__(self) -> None`: store `self._settings = get_settings()`; Qdrant client created lazily in `_get_client()`
  - [x] `_get_client()`: call `get_secret(settings.qdrant_api_key_secret_name)` + construct `AsyncQdrantClient(url=settings.qdrant_url, api_key=key)`
  - [x] Use **`qdrant-client`** library — the async client `qdrant_client.async_qdrant_client.AsyncQdrantClient`
  - [x] Namespace = Qdrant collection name: `{tenant_id}_{agent_id}` (from `namespace` param — never construct it inside the provider)
  - [x] `upsert(namespace, vectors)`: call `client.upsert(collection_name=namespace, points=[...])` using `qdrant_client.models.PointStruct`; create collection if it does not exist via `client.recreate_collection` or `create_collection`; vector size from `len(vectors[0].vector)`; wrap in `ProviderUnavailableError` on any exception
  - [x] `query(namespace, vector, top_k, filters)`: call `client.search(collection_name=namespace, query_vector=vector, limit=top_k, query_filter=...)` — map `filters` dict to Qdrant `Filter(must=[FieldCondition(key=k, match=MatchValue(value=v))])` format; check each result's `payload["namespace"] == namespace` — raise `NamespaceViolationError` if mismatch; return `list[VectorResult]`
  - [x] `delete_namespace(namespace)`: call `client.delete_collection(collection_name=namespace)`; wrap exceptions in `ProviderUnavailableError`
  - [x] `health()`: call `client.get_collections()` — return `True` on success, `False` on exception
  - [x] Store `namespace` in point payload so namespace isolation check can verify it on read

- [x] **Task 3: Register in `app/providers/registry.py`** (AC: 3)
  - [x] Import `QdrantVectorStore` from `app.providers.vector_stores.qdrant`
  - [x] Add `"qdrant": QdrantVectorStore` to `VECTOR_STORE_REGISTRY`

- [x] **Task 4: Extend backend-agnostic VectorStore contract test suite** (AC: 3)
  - [x] File: `tests/providers/vector_stores/test_vector_store_contract.py` (already exists — add Qdrant parametrization)
  - [x] Add `QdrantVectorStore` to the parametrize list
  - [x] Mark Qdrant tests as `@pytest.mark.integration` (require live Qdrant instance or `qdrant/qdrant` Docker image)
  - [x] Mock the async Qdrant client in unit tests using `pytest-mock` — patch `qdrant_client.async_qdrant_client.AsyncQdrantClient`
  - [x] Unit test: `test_qdrant_upsert_calls_client_upsert` — verify `client.upsert()` called with correct collection name
  - [x] Unit test: `test_qdrant_query_namespace_violation` — simulate payload with wrong namespace → assert `NamespaceViolationError` raised
  - [x] Unit test: `test_qdrant_health_returns_false_on_exception` — simulate `get_collections()` exception → assert `health()` returns `False`

- [x] **Task 5: Add ADR for Qdrant backend** (AC: 1)
  - [x] Create `docs/adrs/adr-011-qdrant-vector-store-backend.md`
  - [x] Document: Qdrant Cloud managed, collection-per-namespace, async client, namespace stored in payload for isolation check

- [x] **Task 6: Run regression tests** (AC: 3)
  - [x] `pytest tests/ -x -v --ignore=tests/integration`
  - [x] `mypy --strict app/providers/vector_stores/qdrant.py`

## Dev Notes

### Existing Patterns — Follow Exactly

**PgVectorStore reference** (`app/providers/vector_stores/pgvector.py`):
- Class-level pool initialized lazily with asyncio.Lock
- `ProviderUnavailableError` wraps all external call exceptions
- `NamespaceViolationError` raised on namespace mismatch in query results
- Uses `get_settings()` in `__init__` and `get_secret()` at operation time (not at init)
- Logger: `logger = get_logger(__name__)` from `app/utils/observability.py`

**Abstract VectorStore interface** (locked signatures — never rename):
```python
async def upsert(self, namespace: str, vectors: list[VectorRecord]) -> None: ...
async def query(self, namespace: str, vector: list[float], top_k: int, filters: dict[str, str] | None) -> list[VectorResult]: ...
async def delete_namespace(self, namespace: str) -> None: ...
async def health(self) -> bool: ...
```

**Models** (`app/models/chunk.py`):
- `VectorRecord`: `id: str`, `vector: list[float]`, `text: str`, `metadata: ChunkMetadata`
- `VectorResult`: `id: str`, `score: float`, `text: str`, `metadata: ChunkMetadata`
- `ChunkMetadata`: `tenant_id`, `agent_id`, `document_id`, `chunk_index`, `chunking_strategy`

**Secrets pattern** (from `app/providers/embedding/openai.py`):
```python
api_key = await get_secret(self.settings.qdrant_api_key_secret_name, session=self.aws_session)
```

**Namespace format** (D8 from architecture — never hardcode):
```
{tenant_id}_{agent_id}   # e.g., "abc123_def456"
```
The namespace arrives as a parameter — `QdrantVectorStore` never constructs it.

### VALID_VECTOR_STORES already includes "qdrant"
`app/models/agent.py` already has `VALID_VECTOR_STORES: frozenset[str] = frozenset({"pgvector", "qdrant", "pinecone"})` — no change needed there.

### Qdrant Collection Strategy
One collection per namespace (`{tenant_id}_{agent_id}`). Create the collection on first upsert if it doesn't exist. Use `vectors_config=VectorsConfig(size=dim, distance=Distance.COSINE)`.

### Payload for Namespace Verification
Store `namespace` in each point's payload to enable cross-namespace detection on query results:
```python
PointStruct(
    id=uuid,            # convert record.id to UUID or hash to int
    vector=record.vector,
    payload={"namespace": namespace, "text": record.text, "metadata": record.metadata.model_dump(mode="json")}
)
```
Qdrant point IDs must be `uint64` or UUID — hash `record.id` to UUID: `uuid.UUID(hashlib.md5(record.id.encode()).hexdigest())`.

### qdrant-client Library

Use `qdrant-client>=1.7.0`. Async client: `from qdrant_client import AsyncQdrantClient`.

Key imports:
```python
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
)
```

Add `qdrant-client>=1.7.0` to `requirements.txt`.

### Architecture Guardrails

- NEVER construct namespace inside the provider — it's a parameter
- NEVER call Secrets Manager directly — use `app/utils/secrets.py`
- NEVER use `print()` or stdlib `logging` — use `get_logger(__name__)`
- NEVER raise raw exceptions — wrap in `ProviderUnavailableError` with descriptive message
- NEVER `# type: ignore` in `app/providers/` — fix the type issue

### Project Structure

```
app/
  core/
    config.py                    MODIFY: add qdrant_api_key_secret_name, qdrant_url
  providers/
    registry.py                  MODIFY: import + register QdrantVectorStore
    vector_stores/
      qdrant.py                  NEW: QdrantVectorStore implementation
      __init__.py                MODIFY: export QdrantVectorStore

tests/providers/vector_stores/
  test_vector_store_contract.py  MODIFY: add QdrantVectorStore to parametrize + unit tests

docs/adrs/
  adr-011-qdrant-vector-store-backend.md  NEW

requirements.txt                 MODIFY: add qdrant-client>=1.7.0
```

### References

- Abstract interface: `app/interfaces/vector_store.py`
- Reference implementation: `app/providers/vector_stores/pgvector.py`
- Registry: `app/providers/registry.py`
- Config: `app/core/config.py`
- Secrets: `app/utils/secrets.py`
- Errors: `app/core/errors.py` — `ProviderUnavailableError`, `NamespaceViolationError`
- Models: `app/models/chunk.py` — `VectorRecord`, `VectorResult`, `ChunkMetadata`
- Existing contract tests: `tests/providers/vector_stores/test_vector_store_contract.py`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References
- `.venv/bin/pytest tests/providers/vector_stores/test_vector_store_contract.py -q`
- `.venv/bin/mypy --strict app/providers/vector_stores/qdrant.py`
- `.venv/bin/pytest tests/ -x -v --ignore=tests/integration`

### Completion Notes List
- Implemented `QdrantVectorStore` with lazy secret-backed client creation, collection-per-namespace upsert/query/delete, namespace payload verification, and provider error wrapping.
- Added Qdrant config keys and registry wiring, including vector-store package export updates.
- Extended vector-store contract coverage to include Qdrant backend plus dedicated Qdrant unit assertions.
- Added ADR documenting Qdrant backend decision and updated dependency/test baseline needed for the new backend.

### File List
- app/core/config.py
- app/providers/vector_stores/qdrant.py
- app/providers/vector_stores/__init__.py
- app/providers/registry.py
- tests/providers/vector_stores/test_vector_store_contract.py
- tests/providers/test_registry.py
- tests/core/test_dependencies.py
- docs/adrs/adr-011-qdrant-vector-store-backend.md
- requirements.txt
- requirements-dev.txt
- pyproject.toml

### Change Log
- 2026-05-03: Implemented Story 8.1 Qdrant vector store backend, added tests/ADR, and completed regression + typing validation.
