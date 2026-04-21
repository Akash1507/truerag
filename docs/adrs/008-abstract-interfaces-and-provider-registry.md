# ADR 008: Abstract Interfaces & Provider Registry

**Status:** Accepted  
**Date:** 2026-04-20  
**Story:** 1.8

---

## Context

TrueRAG requires a stable, extensible provider system across five distinct pluggable dimensions:

1. **Vector Store** — where embeddings are persisted and queried
2. **Chunking Strategy** — how documents are split before embedding
3. **Reranker** — optional re-ordering of retrieved chunks before answer generation
4. **Embedding Provider** — which model/service produces vector embeddings
5. **LLM Provider** — which model generates the final answer

New providers must be addable without modifying core pipeline logic (FR54, NFR21). Without a stable abstraction boundary, adding a new backend (e.g., Qdrant alongside PgVector) would require touching service and pipeline code — violating the open/closed principle and creating a regression surface.

Additionally, reranking must be optional from day one. Query pipelines must not carry `if reranker is None` conditionals — a no-op implementation should satisfy the interface contract transparently.

---

## Decision

### 1. Five Abstract Base Classes in `app/interfaces/`

Five ABCs define the complete contract for each pluggable dimension. Method signatures are **locked** — they may not be changed without an ADR update. New capabilities go into new interfaces or implementation-level overloads, never signature changes.

```
VectorStore      — upsert, query, delete_namespace, health  (async)
ChunkingStrategy — chunk                                    (sync)
Reranker         — rerank                                   (sync)
EmbeddingProvider — embed                                   (async)
LLMProvider      — generate                                 (async)
```

`ChunkingStrategy.chunk` and `Reranker.rerank` are synchronous because they are CPU-bound with no I/O. The remaining three are async because they involve network calls.

### 2. Central Registry in `app/providers/registry.py`

A single file maps config string values (as specified in agent YAML) to concrete provider classes:

```python
RERANKER_REGISTRY: dict[str, type[Reranker]] = {"none": PassthroughReranker}
```

Registry values are **types** (classes), not instances. The DI resolver instantiates at request time via `registry["key"]()`. This prevents shared mutable state across requests.

### 3. FastAPI `Depends()` Resolvers in `app/core/dependencies.py`

`app/core/dependencies.py` is the **sole file** permitted to read from registries. All other code (services, pipelines) receives provider instances through FastAPI dependency injection. This enforces the rule: no service or pipeline ever calls `PgVectorStore()` directly.

Resolvers raise `ProviderUnavailableError` for unrecognised config strings, producing a clean 503 rather than an `AttributeError`.

### 4. `PassthroughReranker` as `"none"` Entry

`PassthroughReranker` satisfies the `Reranker` interface and returns all input chunks unchanged, in their original order. It does **not** slice to `top_k` — callers control truncation post-rerank. This makes reranking opt-in without pipeline conditionals: the pipeline always calls `reranker.rerank(...)` regardless of configuration.

---

## Consequences

### Adding a New Provider

Any new provider (e.g., Qdrant) requires exactly **two changes** and zero modifications to services or pipelines:

1. A new class implementing the appropriate ABC:  
   `app/providers/vector_stores/qdrant.py` implementing `VectorStore`

2. One new registry entry:  
   `VECTOR_STORE_REGISTRY["qdrant"] = QdrantVectorStore`

### Constraints

- `app/interfaces/` must never contain concrete implementations
- `app/core/dependencies.py` must be the only file that imports from `app/providers/registry.py`
- mypy strict mode must pass on `app/interfaces/` and `app/providers/` at all times
- `PassthroughReranker.rerank()` must never apply `top_k` slicing — it is a pure passthrough by contract

### Extension Model Example

```
# Step 1: implement the ABC
app/providers/vector_stores/qdrant.py
    class QdrantVectorStore(VectorStore):
        async def upsert(...): ...
        async def query(...): ...
        async def delete_namespace(...): ...
        async def health(...): ...

# Step 2: register
app/providers/registry.py
    VECTOR_STORE_REGISTRY["qdrant"] = QdrantVectorStore
```

No service, pipeline, or router file is touched.

---

## References

- `architecture.md` §Naming Patterns — locked interface method signatures
- `architecture.md` §Enforcement Guidelines — "Never bypass the provider registry"
- `architecture.md` §Pipeline Boundary — "Pipelines call abstract interfaces only"
- `epics.md` §Story 1.8 — FR54, NFR21
