# Story 9.2: Cost-Per-Query Tracking

Status: ready-for-dev

## Story

As a Platform Admin,
I want the cost of every query tracked by component — token usage, embedding API calls, and reranker API calls — stored in a dedicated collection and aggregated per agent,
so that I can identify expensive agents and give teams accurate cost visibility (FR46).

## Acceptance Criteria

1. **Given** a query completes **When** `query_service.py` assembles the response **Then** a cost record is written to the `query_costs` MongoDB collection with: `tenant_id`, `agent_id`, `request_id`, `prompt_tokens`, `completion_tokens`, `embedding_calls`, `reranker_calls`, `timestamp`; cost records are never written to `eval_experiments`

2. **Given** a query that used an LLM provider **When** the provider response is received **Then** prompt token count and completion token count are captured from the provider response and written to the `query_costs` record for that `request_id`

3. **Given** a query that triggered an embedding API call (for the query vector) **When** the embedding call completes **Then** the number of embedding API calls is recorded in the `query_costs` record

4. **Given** a query that used a Cohere reranker **When** reranking completes **Then** the number of reranker API calls is recorded in the `query_costs` record

5. **Given** `GET /v1/metrics` is called **When** cost aggregation runs **Then** the response includes per-agent cost breakdown: total token usage (prompt + completion), total embedding API calls, total reranker API calls aggregated from the `query_costs` collection for the requested time window

## Tasks / Subtasks

- [ ] Task 1: Create `app/utils/cost_tracker.py` — request-scoped cost accumulator (AC: #1, #2, #3, #4)
  - [ ] `QueryCostAccumulator` dataclass: `prompt_tokens: int = 0`, `completion_tokens: int = 0`, `embedding_calls: int = 0`, `reranker_calls: int = 0`
  - [ ] `ContextVar[QueryCostAccumulator | None]` named `_cost_accumulator` with `default=None`
  - [ ] `init_cost_tracking() -> QueryCostAccumulator`: creates new accumulator, sets context var, returns it
  - [ ] `get_cost_accumulator() -> QueryCostAccumulator | None`: returns current accumulator
  - [ ] `record_llm_usage(prompt_tokens: int, completion_tokens: int) -> None`: writes to accumulator if set
  - [ ] `record_embedding_call() -> None`: increments `embedding_calls` if accumulator set
  - [ ] `record_reranker_call() -> None`: increments `reranker_calls` if accumulator set
  - [ ] All functions are no-ops when accumulator is `None` (safe outside query context)

- [ ] Task 2: Create `app/models/query_cost.py` Beanie document (AC: #1)
  - [ ] `QueryCost(Document)` with fields: `tenant_id: str`, `agent_id: str`, `request_id: str`, `prompt_tokens: int = 0`, `completion_tokens: int = 0`, `embedding_calls: int = 0`, `reranker_calls: int = 0`, `timestamp: datetime = Field(default_factory=...)`
  - [ ] `Settings.name = "query_costs"`
  - [ ] `Settings.indexes = [("tenant_id", 1), ("agent_id", 1), ("timestamp", -1)]` for efficient aggregation

- [ ] Task 3: Create `app/db/dao/query_cost_dao.py` (AC: #1)
  - [ ] Follow `IngestionJobDAO` pattern: `QueryCostDAO(BaseDAO[QueryCost])`
  - [ ] Module-level singleton: `query_cost_dao = QueryCostDAO()`
  - [ ] Need `aggregate()` method for cost aggregation — check if `BaseDAO` supports it; add if not

- [ ] Task 4: Register `QueryCost` in Beanie init (`app/main.py`) (AC: #1)
  - [ ] Add `QueryCost` to `document_models` list in `init_beanie()` call
  - [ ] Import `from app.models.query_cost import QueryCost`

- [ ] Task 5: Instrument `AnthropicLLMProvider` to capture token usage (AC: #2)
  - [ ] In `_generate_with_retry()`: the `message` object returned by `client.messages.create()` has `message.usage.input_tokens` and `message.usage.output_tokens`
  - [ ] After successfully extracting text: call `record_llm_usage(message.usage.input_tokens, message.usage.output_tokens)` from `app.utils.cost_tracker`
  - [ ] Do NOT modify `LLMProvider` ABC — only modify `AnthropicLLMProvider` concrete class
  - [ ] Do NOT change the return type of `generate()` or `_generate_with_retry()`

- [ ] Task 6: Instrument `OpenAIEmbedder` to count embedding calls (AC: #3)
  - [ ] In `embed()`: call `record_embedding_call()` once per `_embed_with_retry()` call (one API call = one count regardless of batch size)
  - [ ] Place call after successful response, before returning
  - [ ] Do NOT modify `EmbeddingProvider` ABC

- [ ] Task 7: Instrument `CohereReranker` to count reranker calls (AC: #4)
  - [ ] In `rerank()`: call `record_reranker_call()` once per `_run_coro_sync(_rerank_call())` call
  - [ ] Place call after successful response
  - [ ] Do NOT modify `Reranker` ABC

- [ ] Task 8: Write `QueryCost` record in `app/services/query_service.py` (AC: #1)
  - [ ] Call `init_cost_tracking()` at start of `handle_query()`
  - [ ] After `run_query_pipeline()` returns: read accumulator, create and save `QueryCost` document via `query_cost_dao`
  - [ ] Pass `request_id` from `_request_id_var.get()` (already in context from middleware)
  - [ ] Write is fire-and-forget (use `background_tasks.add_task()` like audit log, or await inline)
  - [ ] On write failure: log error and continue — never fail the query response for a cost record write

- [ ] Task 9: Implement cost aggregation in `app/services/metrics_service.py` (AC: #5)
  - [ ] Create `app/services/metrics_service.py` if it doesn't exist
  - [ ] `async def get_cost_breakdown(time_window_hours: int = 24) -> list[dict]`
  - [ ] MongoDB aggregation pipeline: group by `(tenant_id, agent_id)`, sum all cost fields, filter by `timestamp >= now - time_window`
  - [ ] Returns list of `{tenant_id, agent_id, total_prompt_tokens, total_completion_tokens, total_embedding_calls, total_reranker_calls}`

- [ ] Task 10: Add cost data to `GET /v1/metrics` endpoint (AC: #5)
  - [ ] `app/api/v1/observability.py` already has `/v1/metrics` stub (or add it)
  - [ ] `GET /v1/metrics?window_hours=24` — call `metrics_service.get_cost_breakdown()`
  - [ ] Response includes `costs: [{tenant_id, agent_id, total_prompt_tokens, total_completion_tokens, total_embedding_calls, total_reranker_calls}]`
  - [ ] No auth required on this endpoint (per architecture: unauthenticated infrastructure endpoint)
  - [ ] Note: Story 9.3 will replace/extend this with Prometheus exposition format

- [ ] Task 11: Tests (AC: #1, #2, #3, #4, #5)
  - [ ] `tests/utils/test_cost_tracker.py`: test `init_cost_tracking`, `record_llm_usage`, `record_embedding_call`, `record_reranker_call`, no-op when accumulator is None
  - [ ] `tests/services/test_query_service.py`: assert `QueryCost` written after successful query; assert cost write failure doesn't break query response
  - [ ] `tests/providers/`: mock provider tests verify `record_*` functions called on successful API response

## Dev Notes

### Critical: `LLMProvider` Interface Is Locked — Cannot Return Token Counts

Architecture rule: `app/interfaces/` method signatures locked, never modified. The current `LLMProvider.generate()` returns only `str`. Adding token counts to the return type would require interface change — **do not do this**.

**Solution: Request-scoped `QueryCostAccumulator` via `ContextVar`** (Task 1). Providers write cost data as a side effect without changing their public contract. The accumulator pattern mirrors `ContextVar` usage already established in `app/utils/observability.py` (`_request_id_var`, `_tenant_id_var`, etc.).

The accumulator is `None` by default. Workers, tests, and other callers that don't call `init_cost_tracking()` will safely get no-ops from all `record_*` functions.

### Anthropic Token Data: Where It Lives

In `AnthropicLLMProvider._generate_with_retry()`, `client.messages.create()` returns an `anthropic.types.Message`. The token counts are:

```python
message.usage.input_tokens   # prompt tokens
message.usage.output_tokens  # completion tokens
```

Current implementation (line 46-49) only extracts `message.content[0].text`. Token data is discarded. Fix: extract usage before returning text.

```python
# After successful text extraction, still inside _generate_with_retry:
from app.utils.cost_tracker import record_llm_usage
record_llm_usage(message.usage.input_tokens, message.usage.output_tokens)
```

### OpenAI Embedder: Batch Counting

`OpenAIEmbedder.embed()` batches texts before calling the API. The AC says "number of embedding API calls" — this means count each `_embed_with_retry()` invocation as 1 call regardless of batch size. In the current `embed()` implementation there is no batching loop (it sends all texts in one call), so `record_embedding_call()` called once per `embed()` invocation is correct.

### Cohere Reranker: Sync/Async Pattern

`CohereReranker.rerank()` is synchronous and uses `_run_coro_sync()`. Call `record_reranker_call()` after `_run_coro_sync(_rerank_call(...))` returns successfully.

### `query_costs` vs `eval_experiments` — AC Constraint

AC #1 explicitly states "cost records are never written to `eval_experiments`". This means the RAGAS eval pipeline must NOT accidentally write cost records when running eval queries through the pipeline. Guard: `init_cost_tracking()` is only called in `query_service.handle_query()`, not in `eval_service`. Since accumulator defaults to `None`, eval queries will skip cost recording automatically — but verify eval service doesn't call `handle_query()` directly.

### `GET /v1/metrics` — Split Responsibility with Story 9.3

Story 9.3 implements the Prometheus exposition format for `GET /v1/metrics`. This story implements the cost aggregation that endpoint exposes. In Story 9.2:
- Implement JSON response format: `{"costs": [...], "window_hours": 24}`
- Story 9.3 will either extend this endpoint or replace the response with Prometheus text format

To avoid conflict: implement cost aggregation in `metrics_service.py` (Story 9.2), expose a JSON endpoint at `GET /v1/metrics/costs` or as part of `GET /v1/metrics`. Story 9.3 dev agent should coordinate with this story's implementation.

### `BaseDAO` Aggregate Support

Check `app/db/base_dao.py` for MongoDB aggregation pipeline support. If `BaseDAO` doesn't expose `collection.aggregate()`, add an `aggregate()` method to `QueryCostDAO` directly using `QueryCost.get_motor_collection().aggregate()` (Beanie exposes this via `Document.get_motor_collection()`).

### `request_id` in cost records

`_request_id_var` from `app/utils/observability.py` holds the current request ID (set by `RequestIDMiddleware`). Import it directly: `from app.utils.observability import _request_id_var`. Note: this is a private var (`_` prefix) — if the team prefers, expose a `get_request_id() -> str` helper in `observability.py`.

### `QueryCost` Must Be Registered in `main.py`

Beanie requires all Document models to be registered at init time. Add `QueryCost` to `document_models` in the `init_beanie()` call in `app/main.py` (currently line 39). Missing registration = runtime `CollectionWasNotInitialized` error.

### Story 9.1 Dependency

Story 9.1 (per-stage latency) adds `log_stage_latency()` helper and sets `tenant_id`/`agent_id` context vars in query handler. Story 9.2 depends on the `request_id` context var from `RequestIDMiddleware` (already working). Coordinate if implementing 9.1 and 9.2 in parallel: cost record's `request_id` field comes from `_request_id_var.get()`.

### Project Structure Notes

New files:
- `app/utils/cost_tracker.py` — `QueryCostAccumulator`, context var, `record_*` helpers
- `app/models/query_cost.py` — Beanie document for `query_costs` collection
- `app/db/dao/query_cost_dao.py` — DAO following `IngestionJobDAO` pattern
- `app/services/metrics_service.py` — cost aggregation logic
- `tests/utils/test_cost_tracker.py` — unit tests for accumulator

Modified files:
- `app/main.py` — add `QueryCost` to Beanie `document_models`
- `app/services/query_service.py` — call `init_cost_tracking()`, write `QueryCost` after pipeline
- `app/providers/llm/anthropic.py` — call `record_llm_usage()` from token data in response
- `app/providers/embedding/openai.py` — call `record_embedding_call()`
- `app/providers/rerankers/cohere.py` — call `record_reranker_call()`
- `app/api/v1/observability.py` — add/extend `GET /v1/metrics` with cost breakdown

No interface file changes (`app/interfaces/*.py` are locked).

### References

- FR46: cost-per-query tracking — [Source: planning-artifacts/epics.md#Story 9.2]
- Architecture: "locked method signatures, never modified" — [Source: architecture.md#NFR architectural mechanisms summary]
- Architecture: `app/services/metrics_service.py` — "Cost + latency aggregation, Prometheus formatting" — [Source: architecture.md#Project Structure, line 599]
- Architecture: D1 MongoDB collections (no `query_costs` listed — new collection) — [Source: architecture.md#D1]
- `AnthropicLLMProvider` token data: `app/providers/llm/anthropic.py:40-49`
- `OpenAIEmbedder.embed()`: `app/providers/embedding/openai.py:32-49`
- `CohereReranker.rerank()`: `app/providers/rerankers/cohere.py:46-55`
- ContextVar pattern: `app/utils/observability.py:11-33`
- Beanie document pattern: `app/models/ingestion_job.py`
- DAO pattern: `app/db/dao/ingestion_job_dao.py`

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
