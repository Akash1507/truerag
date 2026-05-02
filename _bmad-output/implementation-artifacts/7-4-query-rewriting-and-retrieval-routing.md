# Story 7.4: Query Rewriting & Retrieval Routing

Status: done

## Story

As a Tenant Developer,
I want optional query rewriting to expand queries for better recall, and automatic routing to skip retrieval for questions the LLM can answer directly,
so that retrieval quality improves for ambiguous queries and latency is reduced for direct-answer queries (FR35, FR36).

## Acceptance Criteria

**AC1 — Query rewriting when enabled**
Given an agent with `query_rewrite: true` in config
When a query arrives
Then `app/pipelines/query/rewriter.py` rewrites the query to improve retrieval recall before the vector store is queried; the rewritten query is used for retrieval; the original query is used for generation context

**AC2 — Query rewriting bypassed when disabled**
Given an agent with `query_rewrite: false` (default)
When a query arrives
Then `rewriter.py` is bypassed entirely; the original query is passed directly to retrieval

**AC3 — Router skips retrieval for direct-answer queries**
Given `app/pipelines/query/router.py` processes a query
When the router determines retrieval is not needed (query answerable from LLM knowledge directly)
Then the vector store is not queried; the LLM generates a response directly; the response includes `citations: []` and a `confidence` score indicating no retrieval was performed

**AC4 — Routing decision is logged**
Given the query routing decision
When logged
Then the structured log entry includes `operation: query_route`, `route: retrieval|direct`, `request_id`, `agent_id`, `tenant_id`

## Tasks / Subtasks

- [x] **Task 1: Add `query_rewrite` field to agent config**
  - [x] File: `app/models/agent.py`
  - [x] Add `query_rewrite: bool = False` to `AgentDocument`, `AgentCreateRequest`, `AgentConfigUpdateRequest`, `AgentCreateResponse`, `AgentUpdateResponse`
  - [x] Default `False` — opt-in feature; existing agents unaffected

- [x] **Task 2: Implement query rewriter**
  - [x] File: `app/pipelines/query/rewriter.py`
  - [ ] Function `async def rewrite_query(query: str, agent: AgentDocument) -> str`
  - [ ] Implementation: call the agent's configured LLM provider (`LLM_REGISTRY`) with a prompt that asks it to expand/rephrase the query for better retrieval recall
  - [ ] Prompt template (embed in rewriter.py as a module-level constant):
    ```
    You are a search query optimizer. Given the following user query, rewrite it to improve 
    retrieval recall by expanding acronyms, adding synonyms, and clarifying ambiguities. 
    Return ONLY the rewritten query — no explanation, no prefix.
    
    Original query: {query}
    Rewritten query:
    ```
  - [ ] Resolve LLM provider via `LLM_REGISTRY[agent.llm_provider]` — do NOT instantiate directly
  - [ ] If rewriting fails (LLM error), log warning and fall back to original query — do NOT raise; rewriting failure must not fail the query
  - [ ] Log: `operation: query_rewrite`, `original_query_len`, `rewritten_query_len`, `latency_ms`, `agent_id`, `tenant_id`

- [x] **Task 3: Implement retrieval router**
  - [x] File: `app/pipelines/query/router.py`
  - [ ] Function `async def route_query(query: str, agent: AgentDocument) -> Literal["retrieval", "direct"]`
  - [ ] Implementation: call LLM with a routing prompt to decide if retrieval is needed
  - [ ] Routing prompt template (module-level constant):
    ```
    You are a query router for a RAG system. Determine if the following query requires 
    document retrieval or can be answered directly from general knowledge.
    
    Query: {query}
    
    Respond with exactly one word: "retrieval" or "direct".
    ```
  - [ ] Parse LLM response: strip whitespace, lowercase; if not "retrieval" or "direct", default to "retrieval" (safe fallback)
  - [ ] Log: `operation: query_route`, `route: retrieval|direct`, `request_id`, `agent_id`, `tenant_id`
  - [ ] `request_id` comes from the calling pipeline context — pass it as a parameter: `async def route_query(query, agent, request_id, tenant_id)`

- [x] **Task 4: Update query pipeline to integrate rewriter and router**
  - [x] File: `app/pipelines/query/pipeline.py`
  - [ ] Add to `run_query_pipeline()` (or equivalent entry function):
    1. **Router step** (always runs, before rewriting or retrieval):
       ```python
       route = await route_query(query, agent, request_id, tenant_id)
       if route == "direct":
           # Skip retrieval entirely
           answer = await llm_provider.generate(query, context=[])
           return QueryResult(answer=answer, citations=[], confidence=0.0)
       ```
    2. **Rewriter step** (only when `agent.query_rewrite == True`):
       ```python
       retrieval_query = query
       if agent.query_rewrite:
           retrieval_query = await rewrite_query(query, agent)
       ```
    3. **Retrieval step** uses `retrieval_query` (rewritten or original)
    4. **Generation step** uses original `query` for context — NOT the rewritten query
  - [ ] Add `router_ms` and (if rewrite enabled) `rewriter_ms` to per-stage latency log in `extra_data`

- [x] **Task 5: Handle direct-route response format**
  - [ ] Ensure `QueryResult` (or equivalent response model) supports `citations: []` and `confidence: 0.0` for direct-route responses
  - [ ] Check `app/models/` for the query response schema — likely already supports these fields (story 5-3 added citations + confidence)
  - [ ] If not: add `citations: list = []` and `confidence: float = 0.0` with appropriate defaults

- [x] **Task 6: Write tests**
  - [ ] `tests/pipelines/query/test_rewriter.py`:
    - Test: `query_rewrite=True` → LLM called with rewrite prompt; rewritten query returned
    - Test: `query_rewrite=False` → not tested here (bypassed at pipeline level, not rewriter level)
    - Test: LLM failure → original query returned (fallback behavior)
    - Mock LLM provider via `AsyncMock`
  - [ ] `tests/pipelines/query/test_router.py`:
    - Test: LLM responds "retrieval" → route is "retrieval"
    - Test: LLM responds "direct" → route is "direct"
    - Test: LLM responds unexpected value → defaults to "retrieval"
    - Test: structured log emitted with `operation: query_route`, `route`, `agent_id`, `tenant_id`
    - Mock LLM provider
  - [ ] `tests/pipelines/query/test_pipeline.py` — add:
    - Test: `route="direct"` → vector_store.query() NOT called; answer returned with `citations=[]`
    - Test: `route="retrieval"`, `query_rewrite=True` → rewriter called before retrieval
    - Test: `route="retrieval"`, `query_rewrite=False` → rewriter NOT called
    - Test: rewriter failure → original query used for retrieval (no exception propagated)

## Dev Notes

### Current State (after Story 7-2 / Story 7-3 in dependency chain)

- `app/pipelines/query/pipeline.py` — dense/sparse/hybrid retrieval, reranker stage; no router or rewriter yet
- `app/models/agent.py` — `query_rewrite` field does NOT exist yet; must be added
- `app/interfaces/llm_provider.py` — `LLMProvider.generate(prompt, context) -> str` (async)
- `LLM_REGISTRY` in `app/providers/registry.py` — `{"anthropic": AnthropicLLMProvider}`
- Query response model (`QueryResult` or similar) — `citations` and `confidence` fields exist from story 5-3

### Story Dependency

This story depends on stories 7-1 (chunking), 7-2 (sparse/hybrid retrieval), and 7-3 (reranking) being complete, as it modifies `app/pipelines/query/pipeline.py` which those stories also modify. Coordinate to avoid merge conflicts, or implement on top of a merged state of those stories.

### Critical: Router Always Runs

The router runs BEFORE the rewriter and retrieval for every query. This adds ~200–500ms LLM latency for direct-answer queries (which then skip retrieval, saving more time). For retrieval queries, total overhead is router_ms + optional rewriter_ms. This is a design tradeoff — document it.

If the team decides router overhead is unacceptable, the router can be made opt-in via a future `query_routing: bool` agent config field. For this story, implement as always-on.

### LLM Provider Integration Pattern

```python
# app/pipelines/query/rewriter.py
from app.providers.registry import LLM_REGISTRY

async def rewrite_query(query: str, agent: AgentDocument) -> str:
    llm_cls = LLM_REGISTRY[agent.llm_provider]
    llm = llm_cls()  # or resolve via Depends() if available in context
    rewrite_prompt = REWRITE_PROMPT_TEMPLATE.format(query=query)
    try:
        rewritten = await llm.generate(rewrite_prompt, context=[])
        return rewritten.strip()
    except Exception:
        logger.warning("query_rewrite_failed", extra={...})
        return query  # fallback
```

**Note**: `LLMProvider.generate(prompt, context)` takes a `prompt: str` and `context: list[Chunk]`. For rewriting/routing, pass `context=[]` (empty context). The LLM implementations should handle empty context gracefully.

### Per-Stage Latency Pattern (from Story 5-5)

```python
# Follow existing pattern exactly
t0 = time.perf_counter()
route = await route_query(...)
router_ms = round((time.perf_counter() - t0) * 1000)

# Add to extra_data dict in final query_pipeline log:
# "extra_data": {"retrieval_ms": ..., "generation_ms": ..., "router_ms": ..., "rewriter_ms": ...}
```

`latency_ms` is top-level in the log entry; per-stage breakdown lives in `extra_data` → appears under `"extra"` key in JSON output.

### Architecture Guardrails — DO NOT VIOLATE

- Always use `app/utils/observability.py` logger with `tenant_id`, `agent_id`, `request_id`, `operation`
- `ProviderUnavailableError` → HTTP 503 — raise if LLM is unavailable for routing (router failure is a hard failure; rewriter failure is a soft failure with fallback)
- Never hardcode the routing or rewrite prompt in the pipeline — keep in `rewriter.py` and `router.py` as module constants
- Never bypass `LLM_REGISTRY` — always resolve LLM provider through registry

### Project Structure Notes

```
app/pipelines/query/
├── pipeline.py      # MODIFY: integrate router + rewriter steps
├── rewriter.py      # NEW: query rewriting logic
├── router.py        # NEW: retrieval routing decision
├── sparse_retriever.py  # from story 7-2
└── rrf.py               # from story 7-2

app/models/
└── agent.py         # MODIFY: add query_rewrite bool field

tests/pipelines/query/
├── test_rewriter.py    # NEW
├── test_router.py      # NEW
└── test_pipeline.py    # MODIFY: add router/rewriter test cases
```

### References

- `app/interfaces/llm_provider.py` — `LLMProvider.generate()` signature
- `app/providers/registry.py` — `LLM_REGISTRY`
- `app/pipelines/query/pipeline.py` — integration point
- `app/models/agent.py` — agent config schema
- Story 5-5 dev notes — per-stage latency log pattern
- Story 5-3 dev notes — query response model with `citations` + `confidence` fields

## Dev Agent Record

### Agent Model Used
GPT-5 Codex

### Debug Log References
- Local `pytest` run for query router/rewriter/pipeline tests

### Completion Notes List
- Router is implemented as hard-fail on unavailable LLM provider (`ProviderUnavailableError`).
- Rewriter is implemented as soft-fail with fallback to original query and warning log.
- Pipeline now runs router first, supports direct route with `citations=[]` and `confidence=0.0`, and includes `router_ms`/`rewriter_ms` stage timings.

### File List
- `app/models/agent.py` — modified (add query_rewrite field)
- `app/pipelines/query/rewriter.py` — created
- `app/pipelines/query/router.py` — created
- `app/pipelines/query/pipeline.py` — modified
- `tests/pipelines/query/test_rewriter.py` — created
- `tests/pipelines/query/test_router.py` — created
- `tests/pipelines/query/test_pipeline.py` — modified

## Change Log

| Date | Change |
|------|--------|
| 2026-05-02 | Story created |
