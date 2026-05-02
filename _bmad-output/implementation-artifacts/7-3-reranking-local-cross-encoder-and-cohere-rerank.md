# Story 7.3: Reranking — Local Cross-Encoder & Cohere Rerank

Status: done

## Story

As a Tenant Developer,
I want to configure a reranker to rescore a wider pool of retrieved chunks before generation,
so that the most relevant chunks surface to the top of the context window regardless of initial retrieval order, using the retrieve-wide-rerank-narrow pattern (FR25).

## Acceptance Criteria

**AC1 — Retrieve-wide-rerank-narrow pattern**
Given a reranker is configured for an agent
When retrieval executes
Then the vector store retrieves `rerank_pool_size` candidates (default: 20, configurable per agent) before passing them to the reranker; the reranker reduces them to `top_k`; the reranker never receives fewer candidates than `top_k`

**AC2 — CrossEncoderReranker scores locally**
Given an agent configured with `reranker: cross_encoder`
When `CrossEncoderReranker.rerank(query, chunks, top_k)` is called with the candidate pool
Then the local cross-encoder model scores each (query, chunk) pair; chunks are returned in descending relevance score order, truncated to `top_k`; no external API call is made

**AC3 — CohereReranker calls Cohere API**
Given an agent configured with `reranker: cohere`
When `CohereReranker.rerank(query, chunks, top_k)` is called with the candidate pool
Then the Cohere Rerank API is called with the query and chunk texts; the Cohere API key is read from AWS Secrets Manager via `secrets.py`; chunks are returned reranked by Cohere's relevance scores, truncated to `top_k`; transient failures are retried via `@retry`

**AC4 — Both rerankers registered in RERANKER_REGISTRY**
Given both rerankers
When registered in `RERANKER_REGISTRY`
Then they are available by config string (`cross_encoder`, `cohere`) alongside the existing `none` (`PassthroughReranker`); switching rerankers requires only a config update — no pipeline code changes

## Tasks / Subtasks

- [x] **Task 1: Write ADR for reranking approach** (before implementation)
  - [x] Create `docs/adrs/adr-009-reranking-cross-encoder-cohere.md`
  - [x] Document: retrieve-wide-rerank-narrow pattern; `rerank_pool_size` agent config field addition
  - [x] Document: cross-encoder model choice — `cross-encoder/ms-marco-MiniLM-L-6-v2` (small, fast, CPU-feasible); sync inference
  - [x] Document: Cohere Rerank API — model `rerank-english-v3.0`; sync HTTP call wrapped in executor; secret from Secrets Manager key `cohere/api_key`

- [x] **Task 2: Add `rerank_pool_size` to agent config**
  - [x] File: `app/models/agent.py`
  - [x] Add `rerank_pool_size: int = Field(default=20, ge=1, le=200)` to `AgentDocument`, `AgentCreateRequest`, `AgentConfigUpdateRequest`, `AgentCreateResponse`, `AgentUpdateResponse`
  - [x] Migration note: existing agents in MongoDB missing this field will default to 20 via Pydantic default

- [x] **Task 3: Implement CrossEncoderReranker**
  - [x] File: `app/providers/rerankers/cross_encoder.py`
  - [x] Class `CrossEncoderReranker(Reranker)` — implements `rerank(query, chunks, top_k) -> list[Chunk]`
  - [x] Use `sentence-transformers` `CrossEncoder` class with model `cross-encoder/ms-marco-MiniLM-L-6-v2`
  - [x] `__init__`: load model once at instantiation — `self._model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")`
  - [x] `rerank()`: call `self._model.predict([(query, chunk.text) for chunk in chunks])`; sort chunks by score descending; return `chunks[:top_k]`
  - [x] Sync method (matches `Reranker` interface which is not async)
  - [x] If `len(chunks) <= top_k`, return all chunks sorted by score (no truncation needed but sort still applies)

- [x] **Task 4: Implement CohereReranker**
  - [x] File: `app/providers/rerankers/cohere.py`
  - [x] Class `CohereReranker(Reranker)` — implements `rerank(query, chunks, top_k) -> list[Chunk]`
  - [x] `__init__`: accept no args (API key fetched at call time)
  - [x] `rerank()`:
    1. Fetch Cohere API key: `api_key = await get_secret("cohere/api_key")` — but wait, `rerank()` is sync per interface; use `asyncio.get_event_loop().run_in_executor(None, ...)` OR fetch key at init via sync path
    2. **Recommended approach**: fetch API key in `__init__` at instantiation time (via `app/utils/secrets.py` sync-compatible wrapper); instantiation happens at request time via registry
    3. Call Cohere Rerank API: `cohere.Client(api_key).rerank(model="rerank-english-v3.0", query=query, documents=[c.text for c in chunks], top_n=top_k)`
    4. Map Cohere response back to original `Chunk` objects in reranked order
    5. Apply `@retry` decorator from `app/utils/retry.py` to the Cohere API call
  - [x] **IMPORTANT**: `Reranker.rerank()` interface is sync — if async secrets access is required, consult the architecture. Use `app/utils/secrets.py` — it may provide a sync-compatible path or the reranker instantiation happens in async context already

- [x] **Task 5: Register both rerankers**
  - [x] File: `app/providers/rerankers/__init__.py` — add exports for new classes
  - [x] File: `app/providers/registry.py` — update `RERANKER_REGISTRY`:
    ```python
    RERANKER_REGISTRY: dict[str, type[Reranker]] = {
        "none": PassthroughReranker,
        "cross_encoder": CrossEncoderReranker,
        "cohere": CohereReranker,
    }
    ```
  - [x] Remove the `# Populated in Epic 7` comment

- [x] **Task 6: Update query pipeline to use rerank_pool_size**
  - [x] File: `app/pipelines/query/pipeline.py`
  - [x] Change retrieval call to fetch `agent.rerank_pool_size` candidates when `agent.reranker != "none"`, else fetch `agent.top_k` candidates
  - [x] After retrieval, call `reranker.rerank(query, retrieved_chunks, top_k=agent.top_k)` — this was already wired in story 5-3; verify `rerank_pool_size` is passed to retrieval, not to reranker
  - [x] Add `reranker_ms` to per-stage latency log (extend story 5-5 pattern in `extra_data`)

- [x] **Task 7: Add dependencies**
  - [x] `pyproject.toml` / `requirements.txt`: add `sentence-transformers>=3.0` (if not already added by story 7-1), `cohere>=5.0`

- [x] **Task 8: Write tests**
  - [x] `tests/providers/rerankers/test_cross_encoder_reranker.py`:
    - Test: chunks returned in descending relevance order (mock `CrossEncoder.predict`)
    - Test: truncated to `top_k`
    - Test: `top_k >= len(chunks)` → all chunks returned (sorted)
    - Mock `CrossEncoder` model — never load real model in tests
  - [x] `tests/providers/rerankers/test_cohere_reranker.py`:
    - Test: Cohere API called with correct query and chunk texts (mock `cohere.Client`)
    - Test: chunks returned in Cohere's reranked order
    - Test: transient Cohere failure → retried via `@retry`
    - Test: Cohere API key fetched from `app/utils/secrets.py` (mock secrets)
  - [x] `tests/providers/rerankers/test_reranker_registry.py` (or add to existing):
    - Test: `RERANKER_REGISTRY["cross_encoder"]` resolves to `CrossEncoderReranker`
    - Test: `RERANKER_REGISTRY["cohere"]` resolves to `CohereReranker`
    - Test: `RERANKER_REGISTRY["none"]` still resolves to `PassthroughReranker` (regression)
  - [x] `tests/pipelines/query/test_pipeline.py` — add:
    - Test: when `reranker != "none"`, retrieval uses `rerank_pool_size` not `top_k`
    - Test: reranker output (`top_k` chunks) passed to generator

## Dev Notes

### Current State (after Story 5-5)

- `app/interfaces/reranker.py` — `Reranker` ABC with `rerank(query, chunks, top_k) -> list[Chunk]` (LOCKED — sync, not async)
- `app/providers/rerankers/passthrough.py` — `PassthroughReranker` exists; returns chunks unchanged
- `app/providers/registry.py` — `RERANKER_REGISTRY = {"none": PassthroughReranker}` with `# Populated in Epic 7` comment
- `app/pipelines/query/pipeline.py` — reranker already wired in story 5-3; currently always `PassthroughReranker`
- `app/utils/secrets.py` — secrets access wrapper; use for Cohere API key
- `app/utils/retry.py` — `@retry` decorator; use for Cohere API calls
- `app/models/agent.py` — `VALID_RERANKERS = {"none", "cross_encoder", "cohere"}` already defined

### Critical: Reranker Interface is Sync

`Reranker.rerank()` is synchronous. This is intentional — cross-encoder inference is CPU-bound. For `CohereReranker`, the Cohere API call is I/O-bound but the interface is sync. Options:
1. Use `requests` (sync HTTP) for Cohere API inside the sync method — simplest
2. Use `httpx` sync client
3. **Do NOT** make `rerank()` async — that would break the interface contract

If secrets access in `__init__` is async-only, instantiate the Cohere client lazily: store the secret key name, fetch via sync boto3 on first call.

### retrieve-wide-rerank-narrow Pattern in Pipeline

```python
# app/pipelines/query/pipeline.py (pseudocode)
pool_size = agent.rerank_pool_size if agent.reranker != "none" else agent.top_k
raw_chunks = await vector_store.query(namespace, query_vector, top_k=pool_size, filters=filters)
reranked_chunks = reranker.rerank(query, raw_chunks, top_k=agent.top_k)
# generator receives reranked_chunks[:agent.top_k]
```

### PassthroughReranker Behavior

`PassthroughReranker.rerank()` does NOT slice to `top_k` — it returns all chunks unchanged. The pipeline must apply `top_k` slicing after calling passthrough reranker. Do not change `PassthroughReranker` — the pipeline already handles this.

### Architecture Guardrails — DO NOT VIOLATE

- Never call `cohere.Client()` directly in services — always via `CohereReranker` resolved through `RERANKER_REGISTRY`
- Never store Cohere API key in plaintext — always fetch via `app/utils/secrets.py`
- Never use `@retry` inline — always import from `app/utils/retry.py`
- `app/utils/observability.py` for all logging — include `operation: rerank`, `reranker`, `chunks_in`, `chunks_out`, `latency_ms`
- p95 query < 3s with reranking (architecture NFR) — cross-encoder on CPU for 20 chunks is ~100–300ms; this is acceptable

### Project Structure Notes

```
app/providers/rerankers/
├── __init__.py          # MODIFY: add new exports
├── passthrough.py       # existing — DO NOT MODIFY
├── cross_encoder.py     # NEW
└── cohere.py            # NEW

app/models/
└── agent.py             # MODIFY: add rerank_pool_size field

app/providers/
└── registry.py          # MODIFY: add cross_encoder and cohere entries

app/pipelines/query/
└── pipeline.py          # MODIFY: use rerank_pool_size; add reranker_ms to latency log

docs/adrs/
└── adr-009-reranking-cross-encoder-cohere.md  # NEW

tests/providers/rerankers/
├── test_cross_encoder_reranker.py  # NEW
└── test_cohere_reranker.py         # NEW
```

### References

- `app/interfaces/reranker.py` — abstract interface (locked — sync)
- `app/providers/rerankers/passthrough.py` — reference pattern
- `app/providers/registry.py` — registry to update
- `app/utils/secrets.py` — secret access wrapper
- `app/utils/retry.py` — retry decorator
- `app/pipelines/query/pipeline.py` — reranker integration point
- Story 5-5 dev notes — `reranker_ms` per-stage latency pattern
- Cohere Rerank API docs: model `rerank-english-v3.0`, `cohere>=5.0` SDK
- sentence-transformers CrossEncoder: `cross-encoder/ms-marco-MiniLM-L-6-v2`

## Dev Agent Record

### Agent Model Used
GPT-5 Codex

### Debug Log References
- `pytest tests/providers/rerankers/test_cross_encoder_reranker.py tests/providers/rerankers/test_cohere_reranker.py tests/providers/rerankers/test_reranker_registry.py tests/providers/test_registry.py tests/pipelines/test_query_pipeline.py -k rerank`

### Completion Notes List
- Added `rerank_pool_size` across agent request/response/document models with defaulting for backward compatibility.
- Implemented `CrossEncoderReranker` and `CohereReranker` with synchronous `rerank()` interface.
- Registered rerankers in registry/package exports and integrated rerank stage + `reranker_ms` in query pipeline.
- Added focused reranker/provider/pipeline tests.
- Added `sentence-transformers` and `cohere` dependencies.

### File List
- `app/models/agent.py` — modified (add rerank_pool_size)
- `app/providers/rerankers/cross_encoder.py` — created
- `app/providers/rerankers/cohere.py` — created
- `app/providers/rerankers/__init__.py` — modified
- `app/providers/registry.py` — modified
- `app/pipelines/query/pipeline.py` — modified
- `docs/adrs/adr-009-reranking-cross-encoder-cohere.md` — created
- `tests/providers/rerankers/test_cross_encoder_reranker.py` — created
- `tests/providers/rerankers/test_cohere_reranker.py` — created
- `tests/providers/rerankers/test_reranker_registry.py` — created
- `tests/pipelines/query/test_pipeline.py` — modified (rerank-related tests only)
- `tests/providers/test_registry.py` — modified
- `pyproject.toml` — modified
- `requirements.txt` — modified

## Change Log

| Date | Change |
|------|--------|
| 2026-05-02 | Story created |
| 2026-05-02 | Story implemented and moved to review |
