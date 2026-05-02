# Story 6.4: Evaluation History & CI-CD Integration

Status: done

## Story

As a Platform Admin,
I want to view evaluation history and score trends per agent, and expose the eval endpoint for CI-CD pipeline integration,
so that quality trends are visible over time and deployments can be blocked on regression (FR43, FR44).

## Acceptance Criteria

**AC1 — Paginated history endpoint returns experiments in descending order**
Given `GET /v1/agents/{agent_id}/eval/history`
When the request is processed
Then a paginated list of experiment records is returned in descending `created_at` order, each including `run_id`, `ragas_scores`, `config_snapshot`, `baseline_delta`, `triggered_alert`, `created_at`; cursor-based pagination applies; response shape: `{"items": [...], "next_cursor": "string | null"}`

**AC2 — CI-CD can use eval/run endpoint without special mode**
Given a CI-CD pipeline calling `POST /v1/agents/{agent_id}/eval/run` with a valid `X-API-Key` header
When the eval run completes synchronously (dataset ≤20 questions)
Then HTTP 200 is returned with full `ragas_scores`; the CI-CD pipeline reads `faithfulness` from the response and fails the pipeline if below threshold — no special CI-CD mode or flag needed

**AC3 — Cross-tenant history access rejected**
Given a valid API key for tenant A requesting history for an agent owned by tenant B
When the request is processed
Then HTTP 403 Forbidden is returned; no experiment records are exposed

## Tasks / Subtasks

- [x] Task 1: Add `EvalHistoryResponse` schema to `app/models/eval.py`
  - [x] 1.1 `EvalExperimentSummary(BaseModel)`: `run_id: str`, `ragas_scores: RAGASScores`, `config_snapshot: dict`, `baseline_delta: float`, `triggered_alert: bool`, `created_at: datetime`
  - [x] 1.2 `EvalHistoryResponse(BaseModel)`: `items: list[EvalExperimentSummary]`, `next_cursor: str | None`

- [x] Task 2: Add `list_experiments` to `app/services/eval_service.py`
  - [x] 2.1 Signature: `list_experiments(agent_id: str, tenant_id: str, cursor: str | None = None, limit: int = 20) -> tuple[list[EvalExperiment], str | None]`
  - [x] 2.2 Call `agent_service.get_agent(agent_id, tenant_id)` — handles 403/404
  - [x] 2.3 Build query: `{"agent_id": agent_id}`; if cursor provided: `decode_cursor(cursor)` then add `{"_id": {"$lt": oid}}` (descending — less than cursor ID since sorted newest-first)
  - [x] 2.4 `docs = await eval_experiment_dao.find(query, sort=[("_id", -1)], limit=limit + 1)`
  - [x] 2.5 Pagination: fetch `limit + 1`, trim to `limit`, encode next_cursor if `len(docs) > limit`
  - [x] 2.6 Return `(docs[:limit], next_cursor)`

- [x] Task 3: Add `GET /v1/agents/{agent_id}/eval/history` to `app/api/v1/eval.py`
  - [x] 3.1 Route: `@router.get("/{agent_id}/eval/history", response_model=EvalHistoryResponse)`
  - [x] 3.2 Query params: `cursor: str | None = Query(default=None)`, `limit: int = Query(default=20, ge=1, le=100)`
  - [x] 3.3 Call `eval_service.list_experiments(agent_id, tenant_id, cursor, limit)`
  - [x] 3.4 Map `EvalExperiment` list → `EvalExperimentSummary` list
  - [x] 3.5 Return `EvalHistoryResponse(items=summaries, next_cursor=next_cursor)`

- [x] Task 4: Write tests
  - [x] 4.1 Add to `tests/api/v1/test_eval.py`:
    - `test_eval_history_returns_paginated_list` — 3 experiments, default limit, assert 200 + items in descending order + `next_cursor` is None
    - `test_eval_history_cursor_pagination` — mock 21 experiments, first page limit=20, assert `next_cursor` is not None; second page with cursor returns remaining item
    - `test_eval_history_cross_tenant_returns_403` — agent belongs to tenant B, assert 403
    - `test_eval_history_empty_returns_empty_list` — no experiments, assert 200 + `items: []` + `next_cursor: null`
  - [x] 4.2 Add to `tests/services/test_eval_service.py`:
    - `test_list_experiments_descending_order` — verify sort=[("_id", -1)] passed to DAO
    - `test_list_experiments_with_cursor` — provide cursor, verify `_id: {$lt: oid}` in query
    - `test_list_experiments_has_next_cursor` — 21 docs returned from DAO, assert next_cursor present + items trimmed to 20
    - `test_list_experiments_forbidden` — agent belongs to different tenant, assert ForbiddenError

- [x] Task 5: Verify CI-CD integration pattern (no code change — documentation check)
  - [x] 5.1 Confirm `POST /v1/agents/{agent_id}/eval/run` already returns `ragas_scores.faithfulness` in the 200 response (implemented in Story 6.2)
  - [x] 5.2 Add comment in `app/api/v1/eval.py` above the `eval/run` route: `# CI-CD: read faithfulness from response, fail pipeline if < threshold. No special mode needed.`
  - [x] 5.3 Verify `X-API-Key` auth works for all eval endpoints (already enforced by `AuthMiddleware` globally — no story-specific work required)

- [x] Task 6: Full epic regression gate — `uv run pytest --tb=short -q` — all tests for epic-6 must pass together
  - [x] 6.1 Run full suite including stories 6.1, 6.2, 6.3, 6.4 test files
  - [x] 6.2 Verify test count increased by ≥20 new tests across the epic

## Dev Notes

### Cursor Pagination — Descending Order

Ascending pagination uses `_id > cursor_id` (used in agents, documents). Descending history uses `_id < cursor_id`:

```python
from app.utils.pagination import decode_cursor, encode_cursor

query: dict[str, object] = {"agent_id": agent_id}
if cursor:
    oid = decode_cursor(cursor)  # raises ValueError → caught as InvalidCursorError at route layer
    query["_id"] = {"$lt": oid}  # less-than for descending order

docs = await eval_experiment_dao.find(query, sort=[("_id", -1)], limit=limit + 1)
```

`encode_cursor(doc.id)` requires `doc.id` (Beanie `PydanticObjectId`). Pattern from agent_service.py:
```python
next_cursor = encode_cursor(docs[-1].id) if has_more and docs and docs[-1].id else None
```

### Route Handler — InvalidCursorError Handling

`decode_cursor` raises `ValueError` on invalid input. Wrap at route layer (same pattern as documents endpoint):

```python
from app.core.errors import InvalidCursorError

@router.get("/{agent_id}/eval/history", response_model=EvalHistoryResponse)
async def get_eval_history(
    agent_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> EvalHistoryResponse:
    tenant_id: str = request.state.tenant_id
    try:
        items, next_cursor = await eval_service.list_experiments(
            agent_id=agent_id,
            tenant_id=tenant_id,
            cursor=cursor,
            limit=limit,
        )
    except ValueError:
        raise InvalidCursorError()
    summaries = [EvalExperimentSummary(...) for e in items]
    return EvalHistoryResponse(items=summaries, next_cursor=next_cursor)
```

### CI-CD Integration Pattern (no code needed)

The eval run endpoint already handles CI-CD use case. Document for users:

```bash
# CI-CD usage example (in GitHub Actions / deploy.yml)
RESPONSE=$(curl -s -X POST \
  "https://api.truerag.io/v1/agents/${AGENT_ID}/eval/run" \
  -H "X-API-Key: ${TRUERAG_API_KEY}")
  
FAITHFULNESS=$(echo $RESPONSE | jq '.ragas_scores.faithfulness')
if (( $(echo "$FAITHFULNESS < 0.6" | bc -l) )); then
  echo "RAGAS faithfulness regression: $FAITHFULNESS < 0.6"
  exit 1
fi
```

No special CI-CD mode. The synchronous 200 path (≤20 questions) is designed for CI-CD pipelines.

### EvalExperimentSummary vs EvalExperiment

`EvalExperiment` is a Beanie document (has MongoDB `_id`, `id` fields). `EvalExperimentSummary` is the API response shape. Map explicitly:

```python
summaries = [
    EvalExperimentSummary(
        run_id=e.run_id,
        ragas_scores=e.ragas_scores,
        config_snapshot=e.config_snapshot,
        baseline_delta=e.baseline_delta,
        triggered_alert=e.triggered_alert,
        created_at=e.created_at,
    )
    for e in experiments
]
```

Do NOT return raw Beanie documents from routes — always map to response models.

### Complete Eval API Surface (summary after all 4 stories)

| Method | Path | Story | Description |
|--------|------|-------|-------------|
| POST | `/v1/agents/{agent_id}/eval` | 6.1 | Upload / replace golden dataset |
| POST | `/v1/agents/{agent_id}/eval/run` | 6.2 | Trigger RAGAS eval run |
| GET | `/v1/agents/{agent_id}/eval/history` | 6.4 | Paginated experiment history |

All routes use prefix `/agents` in `__init__.py` (fixed in Story 6.1). No `/v1/eval/...` routes exist.

### Files to Modify
- `app/models/eval.py` — add EvalExperimentSummary, EvalHistoryResponse
- `app/services/eval_service.py` — add list_experiments
- `app/api/v1/eval.py` — add GET /{agent_id}/eval/history

### References
- [Source: _bmad-output/planning-artifacts/epics.md#Story 6.4] — acceptance criteria
- [Source: _bmad-output/planning-artifacts/architecture.md#Format Patterns] — list response shape `{"items": [], "next_cursor": null}`
- [Source: _bmad-output/planning-artifacts/architecture.md#D11] — cursor = base64 ObjectId, `?cursor=` query param
- [Source: app/utils/pagination.py] — encode_cursor / decode_cursor
- [Source: app/services/agent_service.py#list_agents] — descending pagination pattern with `_id < oid`

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (bmad-dev-story workflow)

### Debug Log References
- `uv run --no-sync pytest --tb=short -q tests/services/test_eval_service.py tests/api/v1/test_eval.py tests/api/v1/test_agents_dao.py`
- `uv run --no-sync pytest --tb=short -q`

### Completion Notes List
- Added `EvalExperimentSummary` and `EvalHistoryResponse` API schemas.
- Implemented `list_experiments` service with descending cursor pagination (`_id < cursor`) and `limit + 1` continuation behavior.
- Added `GET /v1/agents/{agent_id}/eval/history` route with cursor validation and explicit mapping to response DTOs.
- Added CI-CD integration comment above `eval/run` route and preserved existing API-key auth behavior.
- Added API and service tests for history pagination, cursor behavior, forbidden cross-tenant access, and empty results.

### File List
- app/models/eval.py
- app/services/eval_service.py
- app/api/v1/eval.py
- tests/services/test_eval_service.py
- tests/api/v1/test_eval.py
- tests/api/v1/test_agents_dao.py

## Change Log

- 2026-05-02: Story created (ready-for-dev)
- 2026-05-03: Implemented evaluation history endpoint, service pagination, CI-CD guidance comment, and tests; status moved to review.
