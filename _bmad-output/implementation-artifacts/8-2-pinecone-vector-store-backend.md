# Story 8.2: Pinecone Vector Store Backend

Status: ready-for-dev

## Story

As a Tenant Developer,
I want to configure my agent to use Pinecone as its vector store backend,
so that I can use a managed, serverless vector store without operating any infrastructure (FR23).

## Acceptance Criteria

**AC1 — Pinecone upsert stores vectors in namespace-scoped index**
Given an agent configured with `vector_store: pinecone`
When `PineconeVectorStore.upsert(namespace, vectors)` is called
Then vectors are stored in a Pinecone index scoped to namespace `{tenant_id}_{agent_id}`; the Pinecone API key is read from AWS Secrets Manager via `secrets.py`

**AC2 — Pinecone query enforces namespace isolation**
Given `PineconeVectorStore.query(namespace, vector, top_k, filters)`
When called
Then namespace is applied as a hard filter; cross-namespace results are never returned; the same namespace isolation guarantees as pgvector and Qdrant apply

**AC3 — Registered in VECTOR_STORE_REGISTRY and passes backend-agnostic contract tests**
Given `PineconeVectorStore` registered in `VECTOR_STORE_REGISTRY["pinecone"]`
When the backend-agnostic vector store test suite runs against it
Then all assertions pass with only the backend swapped

## Tasks / Subtasks

- [ ] **Task 1: Add Pinecone config to `app/core/config.py`** (AC: 1)
  - [ ] Add `pinecone_api_key_secret_name: str = "truerag/pinecone/api_key"` to `Settings`
  - [ ] Add `pinecone_index_name: str = "truerag"` to `Settings` (one index, namespaces for isolation)

- [ ] **Task 2: Implement `app/providers/vector_stores/pinecone.py`** (AC: 1, 2)
  - [ ] Class `PineconeVectorStore(VectorStore)` — implements full abstract interface
  - [ ] `__init__(self) -> None`: store `self._settings = get_settings()`; Pinecone client created lazily in `_get_index()`
  - [ ] `_get_index()`: call `get_secret(settings.pinecone_api_key_secret_name)` → construct `Pinecone(api_key=key)` → return `pc.Index(settings.pinecone_index_name)`
  - [ ] Use **`pinecone-client`** (package name `pinecone`) — `from pinecone import Pinecone`
  - [ ] **Pinecone namespace strategy**: Use Pinecone's native namespace feature — pass `namespace=namespace` on all upsert/query calls. The Pinecone index is shared; namespaces partition it per agent.
  - [ ] `upsert(namespace, vectors)`: call `index.upsert(vectors=[...], namespace=namespace)` — map `VectorRecord` to `(id, vector, metadata)` tuples where metadata includes `text`, `namespace`, and `ChunkMetadata` fields; wrap exceptions in `ProviderUnavailableError`
  - [ ] `query(namespace, vector, top_k, filters)`: call `index.query(vector=vector, top_k=top_k, namespace=namespace, filter=pinecone_filter, include_metadata=True)`; verify each result's `metadata["namespace"] == namespace` — raise `NamespaceViolationError` on mismatch; reconstruct `VectorResult` from match metadata; wrap exceptions
  - [ ] `delete_namespace(namespace)`: call `index.delete(delete_all=True, namespace=namespace)`; wrap exceptions
  - [ ] `health()`: call `index.describe_index_stats()` — return `True` on success, `False` on exception
  - [ ] **Filters mapping**: Pinecone uses `{"key": {"$eq": "value"}}` format — map `dict[str, str]` filters accordingly

- [ ] **Task 3: Register in `app/providers/registry.py`** (AC: 3)
  - [ ] Import `PineconeVectorStore` from `app.providers.vector_stores.pinecone`
  - [ ] Add `"pinecone": PineconeVectorStore` to `VECTOR_STORE_REGISTRY`

- [ ] **Task 4: Extend backend-agnostic VectorStore contract test suite** (AC: 3)
  - [ ] File: `tests/providers/vector_stores/test_vector_store_contract.py` (already exists — add Pinecone)
  - [ ] Add `PineconeVectorStore` to the parametrize list
  - [ ] Mark Pinecone tests as `@pytest.mark.integration` (require live Pinecone or Localstack equivalent)
  - [ ] Mock the Pinecone client in unit tests — patch `pinecone.Pinecone`
  - [ ] Unit test: `test_pinecone_upsert_passes_namespace` — verify `index.upsert()` called with correct `namespace=`
  - [ ] Unit test: `test_pinecone_query_namespace_violation` — metadata["namespace"] mismatch → `NamespaceViolationError`
  - [ ] Unit test: `test_pinecone_health_returns_false_on_exception` — simulate exception → `False`

- [ ] **Task 5: Add ADR for Pinecone backend** (AC: 1)
  - [ ] Create `docs/adrs/adr-012-pinecone-vector-store-backend.md`
  - [ ] Document: shared index + namespace-per-agent, serverless model, native Pinecone namespaces for isolation

- [ ] **Task 6: Run regression tests** (AC: 3)
  - [ ] `pytest tests/ -x -v --ignore=tests/integration`
  - [ ] `mypy --strict app/providers/vector_stores/pinecone.py`

## Dev Notes

### Existing Patterns — Follow Exactly

**PgVectorStore reference** (`app/providers/vector_stores/pgvector.py`):
- `ProviderUnavailableError` wraps all external call exceptions
- `NamespaceViolationError` raised on namespace mismatch
- Logger: `logger = get_logger(__name__)` from `app/utils/observability.py`
- `get_settings()` in `__init__`, `get_secret()` at operation time (never at startup)

**Story 8.1 (Qdrant)** adds `QdrantVectorStore` first — review it to keep Pinecone consistent.

**Abstract VectorStore interface** (locked):
```python
async def upsert(self, namespace: str, vectors: list[VectorRecord]) -> None: ...
async def query(self, namespace: str, vector: list[float], top_k: int, filters: dict[str, str] | None) -> list[VectorResult]: ...
async def delete_namespace(self, namespace: str) -> None: ...
async def health(self) -> bool: ...
```

**Pinecone namespace vs Qdrant collection approach**:
- Pinecone: one shared index `truerag`, native namespaces partition it — `namespace` param is the Pinecone namespace string
- Qdrant (story 8.1): one collection per namespace
- Both result in the same isolation guarantee; implementation differs

### Pinecone Metadata for Namespace Verification

Store `namespace` in vector metadata so the verification check can confirm isolation:
```python
metadata = {
    "namespace": namespace,
    "text": record.text,
    **record.metadata.model_dump(mode="json"),
}
```

On query, verify: `if match.metadata.get("namespace") != namespace: raise NamespaceViolationError(...)`

### Pinecone Filter Format

```python
# Input: filters = {"source": "manual", "type": "pdf"}
# Pinecone format:
pinecone_filter = {k: {"$eq": v} for k, v in filters.items()} if filters else None
```

### Pinecone async note

The `pinecone-client` library (v3+) uses sync calls internally. Since this is async FastAPI, run index operations in a thread pool to avoid blocking the event loop:
```python
import asyncio
result = await asyncio.get_event_loop().run_in_executor(None, lambda: index.query(...))
```
Or use `asyncio.to_thread(...)` (Python 3.9+).

### pinecone-client Library

Use `pinecone>=3.0.0`. Add to `requirements.txt`.

```python
from pinecone import Pinecone
pc = Pinecone(api_key=api_key)
index = pc.Index(index_name)
```

### VALID_VECTOR_STORES already includes "pinecone"
`app/models/agent.py` already has `VALID_VECTOR_STORES: frozenset[str] = frozenset({"pgvector", "qdrant", "pinecone"})` — no change needed.

### Architecture Guardrails

- NEVER construct namespace inside the provider — it's a parameter
- NEVER call Secrets Manager directly — use `app/utils/secrets.py`
- NEVER use `print()` or stdlib `logging` — use `get_logger(__name__)`
- NEVER raise raw exceptions — wrap in `ProviderUnavailableError`
- NEVER `# type: ignore` in `app/providers/` — fix the type issue
- Both Qdrant (8.1) and Pinecone (8.2) must satisfy the SAME backend-agnostic contract test suite

### Project Structure

```
app/
  core/
    config.py                    MODIFY: add pinecone_api_key_secret_name, pinecone_index_name
  providers/
    registry.py                  MODIFY: import + register PineconeVectorStore
    vector_stores/
      pinecone.py                NEW: PineconeVectorStore implementation
      __init__.py                MODIFY: export PineconeVectorStore

tests/providers/vector_stores/
  test_vector_store_contract.py  MODIFY: add PineconeVectorStore to parametrize + unit tests

docs/adrs/
  adr-012-pinecone-vector-store-backend.md  NEW

requirements.txt                 MODIFY: add pinecone>=3.0.0
```

### References

- Abstract interface: `app/interfaces/vector_store.py`
- Reference implementations: `app/providers/vector_stores/pgvector.py`, `app/providers/vector_stores/qdrant.py` (story 8.1)
- Registry: `app/providers/registry.py`
- Config: `app/core/config.py`
- Secrets: `app/utils/secrets.py`
- Errors: `app/core/errors.py` — `ProviderUnavailableError`, `NamespaceViolationError`
- Models: `app/models/chunk.py` — `VectorRecord`, `VectorResult`, `ChunkMetadata`
- Contract tests: `tests/providers/vector_stores/test_vector_store_contract.py`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
