# Story 1.8: Abstract Interfaces & Provider Registry

Status: done

## Story

As an AI Platform Engineer,
I want all five abstract provider interfaces defined with locked method signatures and a central registry mapping config strings to concrete implementations, including a PassthroughReranker registered for `reranker: none`,
So that all future provider code is registered in one place, pipeline code can never instantiate providers directly, and the query pipeline works without reranking from day one (FR54, NFR21).

## Acceptance Criteria

**AC1:** Given `app/interfaces/` with five abstract base classes
When their method signatures are inspected
Then they exactly match the architecture spec: `VectorStore` (upsert, query, delete_namespace, health), `ChunkingStrategy` (chunk), `Reranker` (rerank), `EmbeddingProvider` (embed), `LLMProvider` (generate); no concrete implementations exist in this directory

**AC2:** Given `app/providers/registry.py`
When inspected
Then it contains five registry dicts (`VECTOR_STORE_REGISTRY`, `CHUNKING_REGISTRY`, `RERANKER_REGISTRY`, `EMBEDDING_REGISTRY`, `LLM_REGISTRY`) mapping config string values to concrete classes; adding a new provider requires only a new entry in this file

**AC3:** Given `reranker: none` in an agent config
When the registry resolves the reranker for that agent
Then a `PassthroughReranker` instance from `app/providers/rerankers/passthrough.py` is returned; calling `rerank(query, chunks, top_k)` on it returns the input chunks unchanged in their original order

**AC4:** Given `app/core/dependencies.py` FastAPI `Depends()` functions
When they resolve provider instances
Then they look up the agent config string in the appropriate registry and return the instance; no service or pipeline file instantiates concrete provider classes directly

**AC5:** Given mypy strict type checking runs on `app/interfaces/` and `app/providers/`
When the check completes
Then all abstract method signatures are satisfied by registered implementations and no type errors are reported

## Tasks / Subtasks

- [x] Task 1: Define five abstract interface ABCs in `app/interfaces/` (AC1, AC5)
  - [x] 1.1 Create `app/interfaces/vector_store.py` — ABC with `upsert`, `query`, `delete_namespace`, `health`
  - [x] 1.2 Create `app/interfaces/chunking_strategy.py` — ABC with `chunk`
  - [x] 1.3 Create `app/interfaces/reranker.py` — ABC with `rerank`
  - [x] 1.4 Create `app/interfaces/embedding_provider.py` — ABC with `embed`
  - [x] 1.5 Create `app/interfaces/llm_provider.py` — ABC with `generate`
  - [x] 1.6 Update `app/interfaces/__init__.py` to re-export all five ABCs

- [x] Task 2: Create supporting Pydantic models (AC1, AC5)
  - [x] 2.1 Create `app/models/chunk.py` — define `ChunkMetadata`, `Chunk`, `VectorRecord`, `VectorResult` Pydantic models used by interface signatures

- [x] Task 3: Implement `PassthroughReranker` (AC3, AC5)
  - [x] 3.1 Create `app/providers/rerankers/passthrough.py` implementing `Reranker` ABC
  - [x] 3.2 `rerank(query, chunks, top_k)` returns input chunks unchanged in original order (no sorting, slicing, or filtering)
  - [x] 3.3 Ensure `PassthroughReranker` satisfies mypy strict: all abstract methods implemented, correct type annotations

- [x] Task 4: Create central provider registry (AC2, AC5)
  - [x] 4.1 Create `app/providers/registry.py` with five registry dicts
  - [x] 4.2 Register `PassthroughReranker` under `"none"` key in `RERANKER_REGISTRY`
  - [x] 4.3 Leave other registries with stub keys pointing to placeholder classes (so mypy sees them populated and type-safe, but actual implementations are deferred to later epics)

- [x] Task 5: Create `app/core/dependencies.py` with FastAPI `Depends()` resolvers (AC4, AC5)
  - [x] 5.1 Create `app/core/dependencies.py` — five `get_*` dependency functions (one per interface type)
  - [x] 5.2 Each resolver reads the agent config (passed as argument or state) and looks up the correct registry
  - [x] 5.3 Raise `ProviderUnavailableError` for unknown config strings not in the registry

- [x] Task 6: Write an ADR (AC1)
  - [x] 6.1 Create `docs/adrs/008-abstract-interfaces-and-provider-registry.md`
  - [x] 6.2 ADR states: locked method signatures, registry pattern, `Depends()` injection, extension model

- [x] Task 7: Write tests (AC1–AC5)
  - [x] 7.1 Create `tests/interfaces/test_interfaces.py` — verify ABCs cannot be instantiated and have the correct abstract methods
  - [x] 7.2 Create `tests/providers/test_passthrough_reranker.py` — verify `rerank()` returns chunks unchanged
  - [x] 7.3 Create `tests/providers/test_registry.py` — verify all five registries are importable and `RERANKER_REGISTRY["none"]` maps to `PassthroughReranker`
  - [x] 7.4 Create `tests/core/test_dependencies.py` — verify dependency resolvers look up correct registry class and raise on unknown key
  - [x] 7.5 Create `tests/interfaces/__init__.py`
  - [x] 7.6 Run `ruff check app/ tests/` — must exit 0 ✅ (story-specific files clean; pre-existing E501 in auth.py unrelated)
  - [x] 7.7 Run `mypy app/interfaces/ app/providers/ --strict` — must exit 0 ✅ (no issues in 15 source files)
  - [x] 7.8 Run `pytest tests/ -v` — all tests must pass ✅ (112 passed, 0 failures)

## Dev Notes

### Critical Architecture Rules (must not violate)

- **Five interfaces ONLY in `app/interfaces/`** — no concrete implementations in this directory ever
- **All provider instantiation ONLY through `app/providers/registry.py`** — no service or pipeline file ever calls `PgVectorStore()`, `OpenAIEmbedder()`, etc. directly; this is the zero-tolerance rule from architecture enforcement guidelines
- **`app/core/dependencies.py` is the ONLY file that reads from registries** — all other code receives provider instances via FastAPI `Depends()`
- **Method signatures are LOCKED** — never add, remove, or rename abstract methods in `app/interfaces/`; new capabilities go into new interfaces or new method overloads in concrete classes only
- **mypy strict must pass** — `app/interfaces/` and `app/providers/` are type-annotated at the same level as the rest of the codebase
- **`PassthroughReranker.rerank()` is a pure passthrough** — it does NOT slice to `top_k`; it returns chunks unchanged; the caller decides whether to apply `top_k` post-rerank
- **Do NOT add `app/models/agent.py` yet** — that is Story 2.3; the agent config model is not needed here; use a minimal dataclass/TypedDict for the dependency resolver prototype
- **Do NOT create any route files** — this story is infrastructure (interfaces + registry + DI skeleton) only; no API endpoints

### Abstract Interface Method Signatures (LOCKED — exact spec from architecture.md)

```python
# app/interfaces/vector_store.py
class VectorStore(ABC):
    @abstractmethod
    async def upsert(self, namespace: str, vectors: list[VectorRecord]) -> None: ...
    @abstractmethod
    async def query(
        self, namespace: str, vector: list[float], top_k: int, filters: dict[str, str] | None
    ) -> list[VectorResult]: ...
    @abstractmethod
    async def delete_namespace(self, namespace: str) -> None: ...
    @abstractmethod
    async def health(self) -> bool: ...

# app/interfaces/chunking_strategy.py
class ChunkingStrategy(ABC):
    @abstractmethod
    def chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]: ...

# app/interfaces/reranker.py
class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]: ...

# app/interfaces/embedding_provider.py
class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

# app/interfaces/llm_provider.py
class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, context: list[Chunk]) -> str: ...
```

> **Note on async vs sync:** `ChunkingStrategy.chunk` and `Reranker.rerank` are sync (CPU-bound, no I/O). `VectorStore`, `EmbeddingProvider`, `LLMProvider` are async (network I/O). This matches the architecture doc exactly.

### Shared Models: `app/models/chunk.py`

These types are used by interface signatures across multiple ABCs. Create them FIRST before writing any interface file.

```python
# app/models/chunk.py
from datetime import datetime
from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    tenant_id: str
    agent_id: str
    document_id: str
    chunk_index: int
    chunking_strategy: str
    timestamp: datetime
    version: int


class Chunk(BaseModel):
    text: str
    metadata: ChunkMetadata


class VectorRecord(BaseModel):
    id: str          # unique ID for the vector (e.g. f"{document_id}_{chunk_index}")
    vector: list[float]
    metadata: ChunkMetadata
    text: str        # stored for retrieval response reconstruction


class VectorResult(BaseModel):
    id: str
    score: float
    metadata: ChunkMetadata
    text: str
```

> **Important:** We do NOT import from `app/models/agent.py` because it doesn't exist yet. The dependency resolver in `app/core/dependencies.py` for this story uses a minimal string argument, not a full agent config model.

### Registry Implementation: `app/providers/registry.py`

```python
# app/providers/registry.py
from app.interfaces.chunking_strategy import ChunkingStrategy
from app.interfaces.embedding_provider import EmbeddingProvider
from app.interfaces.llm_provider import LLMProvider
from app.interfaces.reranker import Reranker
from app.interfaces.vector_store import VectorStore
from app.providers.rerankers.passthrough import PassthroughReranker

VECTOR_STORE_REGISTRY: dict[str, type[VectorStore]] = {
    # Populated in later epics: "pgvector": PgVectorStore, "qdrant": ..., "pinecone": ...
}

CHUNKING_REGISTRY: dict[str, type[ChunkingStrategy]] = {
    # Populated in Epic 4: "fixed_size": FixedSizeChunker, ...
}

RERANKER_REGISTRY: dict[str, type[Reranker]] = {
    "none": PassthroughReranker,
    # Populated in Epic 7: "cross_encoder": ..., "cohere": ...
}

EMBEDDING_REGISTRY: dict[str, type[EmbeddingProvider]] = {
    # Populated in Epic 4: "openai": OpenAIEmbedder, ...
}

LLM_REGISTRY: dict[str, type[LLMProvider]] = {
    # Populated in Epic 5: "anthropic": AnthropicProvider, ...
}
```

**Key design decision:** Registry values are **types** (classes), not instances. The DI resolver instantiates them at request time via `registry["key"]()`. This ensures provider instances are not shared across requests (no shared state risk).

### PassthroughReranker Implementation

```python
# app/providers/rerankers/passthrough.py
from app.interfaces.reranker import Reranker
from app.models.chunk import Chunk


class PassthroughReranker(Reranker):
    """No-op reranker for agents configured with reranker: none.
    Returns chunks unchanged in their original order."""

    def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
        # Pure passthrough — do NOT slice to top_k here.
        # Caller applies top_k filtering after retrieval if needed.
        return chunks
```

### `app/core/dependencies.py` — Dependency Resolver Skeleton

For Story 1.8, the dependency functions accept a `provider_key` string (the config value for the provider type) and return an instance. Story 2+ will wire these to the actual agent config model via `Depends()`.

```python
# app/core/dependencies.py
from app.core.errors import ErrorCode, ProviderUnavailableError
from app.interfaces.chunking_strategy import ChunkingStrategy
from app.interfaces.embedding_provider import EmbeddingProvider
from app.interfaces.llm_provider import LLMProvider
from app.interfaces.reranker import Reranker
from app.interfaces.vector_store import VectorStore
from app.providers.registry import (
    CHUNKING_REGISTRY,
    EMBEDDING_REGISTRY,
    LLM_REGISTRY,
    RERANKER_REGISTRY,
    VECTOR_STORE_REGISTRY,
)


def get_vector_store(vector_store_key: str) -> VectorStore:
    cls = VECTOR_STORE_REGISTRY.get(vector_store_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown vector store provider: {vector_store_key!r}"
        )
    return cls()


def get_chunker(chunking_key: str) -> ChunkingStrategy:
    cls = CHUNKING_REGISTRY.get(chunking_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown chunking strategy: {chunking_key!r}"
        )
    return cls()


def get_reranker(reranker_key: str) -> Reranker:
    cls = RERANKER_REGISTRY.get(reranker_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown reranker: {reranker_key!r}"
        )
    return cls()


def get_embedder(embedding_key: str) -> EmbeddingProvider:
    cls = EMBEDDING_REGISTRY.get(embedding_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown embedding provider: {embedding_key!r}"
        )
    return cls()


def get_llm_provider(llm_key: str) -> LLMProvider:
    cls = LLM_REGISTRY.get(llm_key)
    if cls is None:
        raise ProviderUnavailableError(
            message=f"Unknown LLM provider: {llm_key!r}"
        )
    return cls()
```

> **Future wiring (Story 2+):** These functions will be wrapped with `Depends()` and wired to agent config. For example: `def get_reranker_for_agent(agent: AgentDocument = Depends(get_current_agent)) -> Reranker: return get_reranker(agent.reranker)`. Do NOT implement that wiring now — keep this simple for 1.8.

### mypy Strict Notes

- `ABC` and `abstractmethod` from `abc` stdlib — no third-party imports needed
- `list[Chunk]` return type annotation in `rerank` — do NOT use `List[Chunk]` (use built-in generic, Python 3.9+; ruff UP006)
- `dict[str, str] | None` — use union syntax, not `Optional[Dict[str, str]]` (ruff UP006, UP007)
- `type[VectorStore]` for registry values — `type[X]` is the correct annotation for a class (not an instance)
- Proto implementations that appear in stubs (e.g., `PassthroughReranker`) must implement ALL abstract methods or mypy will flag `error: Cannot instantiate abstract class`
- Do NOT use `TYPE_CHECKING` guards for imports in `registry.py` — the import is always needed at runtime since registry values are classes

### Test Patterns

```python
# tests/interfaces/test_interfaces.py
import pytest
from app.interfaces.vector_store import VectorStore
from app.interfaces.chunking_strategy import ChunkingStrategy
from app.interfaces.reranker import Reranker
from app.interfaces.embedding_provider import EmbeddingProvider
from app.interfaces.llm_provider import LLMProvider

def test_vector_store_is_abstract() -> None:
    with pytest.raises(TypeError):
        VectorStore()  # type: ignore[abstract]

def test_chunking_strategy_is_abstract() -> None:
    with pytest.raises(TypeError):
        ChunkingStrategy()  # type: ignore[abstract]

def test_reranker_is_abstract() -> None:
    with pytest.raises(TypeError):
        Reranker()  # type: ignore[abstract]

def test_embedding_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        EmbeddingProvider()  # type: ignore[abstract]

def test_llm_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


# tests/providers/test_passthrough_reranker.py
from app.providers.rerankers.passthrough import PassthroughReranker
from app.models.chunk import Chunk, ChunkMetadata
from datetime import datetime, UTC


def _make_chunk(index: int) -> Chunk:
    return Chunk(
        text=f"chunk {index}",
        metadata=ChunkMetadata(
            tenant_id="t1",
            agent_id="a1",
            document_id="d1",
            chunk_index=index,
            chunking_strategy="fixed_size",
            timestamp=datetime.now(UTC),
            version=1,
        ),
    )


def test_passthrough_reranker_returns_unchanged() -> None:
    reranker = PassthroughReranker()
    chunks = [_make_chunk(0), _make_chunk(1), _make_chunk(2)]
    result = reranker.rerank(query="test", chunks=chunks, top_k=2)
    assert result == chunks  # same order, all chunks (no slicing)

def test_passthrough_reranker_empty_input() -> None:
    reranker = PassthroughReranker()
    result = reranker.rerank(query="test", chunks=[], top_k=5)
    assert result == []


# tests/providers/test_registry.py
from app.providers.registry import (
    VECTOR_STORE_REGISTRY,
    CHUNKING_REGISTRY,
    RERANKER_REGISTRY,
    EMBEDDING_REGISTRY,
    LLM_REGISTRY,
)
from app.providers.rerankers.passthrough import PassthroughReranker

def test_reranker_registry_has_none_key() -> None:
    assert "none" in RERANKER_REGISTRY
    assert RERANKER_REGISTRY["none"] is PassthroughReranker

def test_all_five_registries_importable() -> None:
    assert isinstance(VECTOR_STORE_REGISTRY, dict)
    assert isinstance(CHUNKING_REGISTRY, dict)
    assert isinstance(RERANKER_REGISTRY, dict)
    assert isinstance(EMBEDDING_REGISTRY, dict)
    assert isinstance(LLM_REGISTRY, dict)

def test_none_key_returns_instance() -> None:
    reranker = RERANKER_REGISTRY["none"]()
    assert isinstance(reranker, PassthroughReranker)


# tests/core/test_dependencies.py
import pytest
from app.core.dependencies import get_reranker
from app.core.errors import ProviderUnavailableError
from app.providers.rerankers.passthrough import PassthroughReranker

def test_get_reranker_none_returns_passthrough() -> None:
    result = get_reranker("none")
    assert isinstance(result, PassthroughReranker)

def test_get_reranker_unknown_raises_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError):
        get_reranker("unknown_reranker")

def test_get_vector_store_unknown_raises() -> None:
    from app.core.dependencies import get_vector_store
    with pytest.raises(ProviderUnavailableError):
        get_vector_store("unknown_store")
```

### ADR Format for `docs/adrs/008-abstract-interfaces-and-provider-registry.md`

- **Status:** Accepted
- **Context:** TrueRAG requires a stable, extensible provider system across 5 distinct pluggable dimensions (vector store, chunking, reranking, embedding, LLM). New providers must be addable without modifying core pipeline logic (FR54, NFR21).
- **Decision:** Five abstract base classes (ABCs) in `app/interfaces/` with locked method signatures. A central registry in `app/providers/registry.py` maps config string values to concrete classes. All provider instantiation goes through FastAPI `Depends()` functions in `app/core/dependencies.py`. `PassthroughReranker` registered as `"none"` to make reranking optional from day one without pipeline conditionals.
- **Consequences:** Any new provider (vector store, embedder, etc.) requires: (1) a new class implementing the appropriate ABC, and (2) one new entry in the corresponding registry dict. Zero changes to services or pipelines.
- **Extension model example:** Adding Qdrant requires: `app/providers/vector_stores/qdrant.py` implementing `VectorStore`, and `VECTOR_STORE_REGISTRY["qdrant"] = QdrantVectorStore`.

### Anti-Patterns to Avoid

- **Do NOT create placeholder/stub concrete classes for empty registries** — leave empty dicts; mypy is happy with `dict[str, type[VectorStore]] = {}`
- **Do NOT slice `top_k` in `PassthroughReranker.rerank`** — it's a pure passthrough; upstream retrieval already limits results to `top_k` before calling `rerank`; the interface contract says "rerank N items, return N items (or fewer if filtered)"
- **Do NOT import concrete providers from `app/services/` or `app/pipelines/`** — only `app/core/dependencies.py` touches the registry
- **Do NOT use `@dataclass` for `ChunkMetadata`, `Chunk`, etc.** — use Pydantic `BaseModel` for consistency with every other model in the codebase
- **Do NOT create `app/models/agent.py`** — Story 2.3
- **Do NOT create any `app/api/v1/*.py` routes** — this story has no API surface
- **Do NOT add `app/providers/vector_stores/pgvector.py`** — Story 4 (Epic 4)
- **Do NOT add `app/providers/embedding/openai.py`** — Story 4 (Epic 4)
- **Do NOT add `app/providers/llm/anthropic.py`** — Story 5 (Epic 5)

### File Locations

```
app/interfaces/vector_store.py          ← NEW: VectorStore ABC
app/interfaces/chunking_strategy.py    ← NEW: ChunkingStrategy ABC
app/interfaces/reranker.py             ← NEW: Reranker ABC
app/interfaces/embedding_provider.py   ← NEW: EmbeddingProvider ABC
app/interfaces/llm_provider.py         ← NEW: LLMProvider ABC
app/interfaces/__init__.py             ← MODIFIED: re-export all five ABCs

app/models/chunk.py                    ← NEW: ChunkMetadata, Chunk, VectorRecord, VectorResult

app/providers/rerankers/passthrough.py ← NEW: PassthroughReranker
app/providers/registry.py              ← NEW: five registry dicts

app/core/dependencies.py               ← NEW: five get_*() resolver functions

docs/adrs/008-abstract-interfaces-and-provider-registry.md  ← NEW: ADR

tests/interfaces/__init__.py           ← NEW
tests/interfaces/test_interfaces.py    ← NEW: ABC instantiation tests
tests/providers/test_passthrough_reranker.py  ← NEW: PassthroughReranker tests
tests/providers/test_registry.py       ← NEW: registry lookup tests
tests/core/test_dependencies.py        ← NEW: DI resolver tests
```

### Dependencies Already in requirements.txt

No new runtime dependencies needed. All required packages are already present:
- `abc` — Python standard library
- `pydantic` — already in `requirements.txt` (used by `app/models/tenant.py`)
- Standard `typing` stdlib

### Previous Story Learnings (from Stories 1.5–1.7)

- **Use `from datetime import UTC`** (Python 3.11+) — `datetime.now(UTC)` not `datetime.now(datetime.timezone.UTC)` (ruff-friendly; Story 1.7 established this)
- **Use `from collections.abc import ...`** not `from typing import ...` for `Callable`, `AsyncGenerator`, etc. (ruff UP035)
- **Ruff I001 import order:** stdlib → third-party → first-party (`app.*`) with blank lines between each group; no mixing groups
- **Use built-in generics**: `list[X]`, `dict[K,V]`, `type[X]` — NOT `List[X]`, `Dict[K,V]`, `Type[X]` (ruff UP006)
- **Use `X | None`** — NOT `Optional[X]` (ruff UP007)
- **Never `print()` or `import logging` directly** — use `get_logger(__name__)` from `app/utils/observability.py` (but this story has no logging paths)
- **Module-level state in tests:** use `autouse=True` fixtures to clean up any module-level state between tests (e.g., `_counters` from rate_limiter)
- **`# type: ignore[abstract]`** — needed when constructing abstract classes in tests to satisfy mypy; instantiation still raises `TypeError` at runtime as expected
- **`app/models/tenant.py` uses `rate_limit_rpm: int | None = None`** — Story 1.7 review changed from `int = 60` to avoid masking absent MongoDB fields; follow the same nullable pattern for optional model fields

### Project Structure Context

Current `app/` directory state after Stories 1.1–1.7:
- `app/core/`: `auth.py`, `config.py`, `dependencies.py` ← **empty placeholder only — this story creates it**; `errors.py`, `exception_handlers.py`, `middleware.py`, `rate_limiter.py`
- `app/interfaces/`: only `__init__.py` (empty stub) — **all interface files created in this story**
- `app/models/`: only `tenant.py` — **`chunk.py` created in this story**
- `app/providers/`: only subdirectory `__init__.py` stubs — **`registry.py` and `rerankers/passthrough.py` created in this story**
- `app/utils/`: `observability.py`, `pii.py`, `retry.py`, `secrets.py`
- `tests/`: 85 existing tests across `core/`, `utils/`, `api/v1/`, `test_main.py`

> **Check first:** Verify `app/core/dependencies.py` doesn't already exist before creating it. If it does, inspect contents carefully before overwriting. Based on current codebase scan: it does NOT exist yet.

### References

- [Source: architecture.md#Naming Patterns] — Abstract interface method signatures LOCKED: `VectorStore` (upsert, query, delete_namespace, health), `ChunkingStrategy` (chunk), `Reranker` (rerank), `EmbeddingProvider` (embed), `LLMProvider` (generate)
- [Source: architecture.md#Structure Patterns] — Provider registration in `app/providers/registry.py`; `VECTOR_STORE_REGISTRY: dict[str, type[VectorStore]]` pattern
- [Source: architecture.md#Enforcement Guidelines] — "Never bypass the provider registry — instantiate providers only through `app/providers/registry.py`"
- [Source: architecture.md#Pipeline Boundary] — "Pipelines call abstract interfaces only — never concrete provider classes"
- [Source: architecture.md#Project Structure] — Full directory spec; `app/interfaces/` for ABCs, `app/providers/` for concrete, `app/core/dependencies.py` for DI
- [Source: epics.md#Story 1.8] — User story statement and 5 acceptance criteria
- [Source: story 1.7 dev notes] — Middleware, import order, ruff patterns, test patterns carried forward
- [Source: architecture.md#D8] — Namespace format: `{tenant_id}_{agent_id}` — relevant for VectorStore method signature context

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (Thinking)

### Debug Log References

- Fixed unused `pytest` import in `tests/providers/test_passthrough_reranker.py` (ruff F401). Pre-existing E501 in `app/core/auth.py` is unrelated to this story and was not introduced here.

### Completion Notes List

- Implemented all five ABCs (`VectorStore`, `ChunkingStrategy`, `Reranker`, `EmbeddingProvider`, `LLMProvider`) with locked method signatures per architecture spec (AC1)
- Created `app/models/chunk.py` with `ChunkMetadata`, `Chunk`, `VectorRecord`, `VectorResult` Pydantic models shared across interface signatures (AC1)
- Implemented `PassthroughReranker` as a pure no-op: returns all input chunks unchanged, does not slice to `top_k` (AC3)
- Created central `app/providers/registry.py` with five typed registry dicts; only `RERANKER_REGISTRY["none"]` populated in this story (AC2)
- Created `app/core/dependencies.py` with five `get_*()` resolver functions; all raise `ProviderUnavailableError` for unknown keys (AC4)
- All validations passed: mypy strict (0 issues, 15 files), ruff clean on all story files, 112 pytest tests passing (27 new + 85 existing, 0 regressions)
- ADR 008 documents the registry pattern, locked signatures, DI resolver boundary, and extension model

### File List

- `app/interfaces/vector_store.py` — NEW
- `app/interfaces/chunking_strategy.py` — NEW
- `app/interfaces/reranker.py` — NEW
- `app/interfaces/embedding_provider.py` — NEW
- `app/interfaces/llm_provider.py` — NEW
- `app/interfaces/__init__.py` — MODIFIED (re-exports all five ABCs)
- `app/models/chunk.py` — NEW
- `app/providers/rerankers/passthrough.py` — NEW
- `app/providers/registry.py` — NEW
- `app/core/dependencies.py` — NEW
- `docs/adrs/008-abstract-interfaces-and-provider-registry.md` — NEW
- `tests/interfaces/__init__.py` — NEW
- `tests/interfaces/test_interfaces.py` — NEW
- `tests/providers/test_passthrough_reranker.py` — NEW
- `tests/providers/test_registry.py` — NEW
- `tests/core/test_dependencies.py` — NEW

### Review Findings

- [x] [Review][Patch] `ChunkMetadata.timestamp` accepts naive `datetime` — no timezone enforcement; use Pydantic v2 `AwareDatetime` or `datetime_validator` [`app/models/chunk.py:12`]
- [x] [Review][Patch] `ChunkMetadata.chunk_index` and `version` allow negative integers — add `Field(ge=0)` constraints [`app/models/chunk.py:9,13`]
- [x] [Review][Patch] `test_passthrough_reranker_returns_unchanged` uses `==` not `is` — weaker assertion doesn't verify the no-copy passthrough contract [`tests/providers/test_passthrough_reranker.py:26`]
- [x] [Review][Defer] `get_*()` calls `cls()` with no arguments — future concrete providers with required init params will raise `TypeError` [`app/core/dependencies.py`] — deferred, by design; Story 2+ wires config injection
- [x] [Review][Defer] Registry mutable globals with no write protection — any module can corrupt the registry at runtime [`app/providers/registry.py`] — deferred, Python registry idiom; mypy strict enforces types statically
- [x] [Review][Defer] `PassthroughReranker.rerank()` ignores `top_k` with no validation for `top_k <= 0` [`app/providers/rerankers/passthrough.py`] — deferred, pure passthrough by design; concrete rerankers (Epic 7) define their own guards
- [x] [Review][Defer] Interface contracts for empty inputs (`chunk("")`, `embed([])`, `upsert([])`) are unspecified [`app/interfaces/`] — deferred, concrete providers (Epics 4–5) define behavior
- [x] [Review][Defer] `VectorRecord.vector` has no `min_length=1` constraint; `VectorResult.score` has no finite-float validation [`app/models/chunk.py`] — deferred, provider-specific; Epic 4 adds concrete validation

## Change Log

- 2026-04-20: Implemented Story 1.8 — five abstract interfaces, shared Pydantic models, PassthroughReranker, central provider registry, FastAPI DI resolvers, ADR 008, and full test suite (27 new tests). All 112 tests passing, mypy strict clean, ruff clean on story files. Status set to review.
- 2026-04-20: Code review completed — 3 patch findings, 5 deferred. Status remains in-progress pending patches.
