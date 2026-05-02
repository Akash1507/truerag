# Story 6.1: Golden Dataset Management

Status: done

## Story

As a Tenant Developer,
I want to define and store a golden dataset of question/answer pairs per agent,
so that I have a stable evaluation baseline to measure retrieval quality against (FR39).

## Acceptance Criteria

**AC1 — Dataset stored, HTTP 201 returned**
Given `POST /v1/agents/{agent_id}/eval` with body `{"questions": [{"question": "...", "expected_answer": "..."}, ...]}`
When the request is processed
Then the golden dataset is stored in the `eval_datasets` MongoDB collection with `agent_id`, `tenant_id`, `questions[]`, `created_at`; HTTP 201 is returned with the dataset ID

**AC2 — Existing dataset replaced, cache invalidated**
Given an agent that already has a golden dataset
When a new dataset is uploaded via `POST /v1/agents/{agent_id}/eval`
Then the existing dataset is replaced (upsert by `agent_id`); `semantic_cache.invalidate(agent_id)` is called (no-op until Epic 8); HTTP 201 returned with the new dataset ID

**AC3 — Cross-tenant upload rejected**
Given a valid API key for tenant A trying to upload a dataset to an agent owned by tenant B
When the request is processed
Then HTTP 403 Forbidden is returned with `error.code == "FORBIDDEN"`; no dataset is stored and no cache invalidation occurs

## Tasks / Subtasks

- [x] Task 1: Create `app/models/eval.py` — EvalDataset Beanie document + request/response schemas
  - [x] 1.1 `EvalQuestion(BaseModel)`: `question: str`, `expected_answer: str`
  - [x] 1.2 `EvalDataset(Document)`: Beanie document; fields: `agent_id: str`, `tenant_id: str`, `questions: list[EvalQuestion]`, `created_at: datetime`; `class Settings: name = "eval_datasets"`
  - [x] 1.3 `EvalDatasetCreateRequest(BaseModel)`: `questions: list[EvalQuestion]` with `Field(min_length=1)`
  - [x] 1.4 `EvalDatasetCreateResponse(BaseModel)`: `dataset_id: str`, `agent_id: str`, `tenant_id: str`, `question_count: int`, `created_at: datetime`

- [x] Task 2: Create `app/db/dao/eval_dataset_dao.py`
  - [x] 2.1 `EvalDatasetDAO(BaseDAO[EvalDataset])` with `__init__(self) -> None: super().__init__(EvalDataset)`
  - [x] 2.2 `eval_dataset_dao = EvalDatasetDAO()` module-level singleton (same pattern as `agent_dao.py`)

- [x] Task 3: Create `app/services/eval_service.py`
  - [x] 3.1 Import logger: `from app.utils.observability import get_logger; logger = get_logger(__name__)`
  - [x] 3.2 `create_or_replace_dataset(agent_id: str, tenant_id: str, questions: list[EvalQuestion]) -> EvalDataset`
    - [x] 3.2.1 Call `await agent_service.get_agent(agent_id, tenant_id)` — raises `AgentNotFoundError` (404) or `ForbiddenError` (403) automatically
    - [x] 3.2.2 Check if existing dataset: `existing = await eval_dataset_dao.find_one({"agent_id": agent_id})`
    - [x] 3.2.3 If existing: call `await existing.delete()` then create new; this is an explicit replace not an upsert
    - [x] 3.2.4 Create new `EvalDataset(agent_id=agent_id, tenant_id=tenant_id, questions=questions, created_at=datetime.now(UTC))`
    - [x] 3.2.5 `await eval_dataset_dao.insert_one(dataset)` 
    - [x] 3.2.6 `from app.utils import semantic_cache; await semantic_cache.invalidate(agent_id)` — always, even on first create (no-op stub until Epic 8, call sites identical)
    - [x] 3.2.7 Log: `logger.info("eval_dataset_replaced", extra={"operation": "eval_dataset_replace", "extra_data": {"agent_id": agent_id, "tenant_id": tenant_id, "question_count": len(questions)}})`
    - [x] 3.2.8 Return the new dataset

- [x] Task 4: Expand `app/api/v1/eval.py` — add POST endpoint
  - [x] 4.1 Add `POST /{agent_id}/eval` route — status_code=201
  - [x] 4.2 Extract `tenant_id` from `request.state.tenant_id` (set by `AuthMiddleware`)
  - [x] 4.3 Call `eval_service.create_or_replace_dataset(...)` and return `EvalDatasetCreateResponse`

- [x] Task 5: Fix router prefix bug in `app/api/v1/__init__.py`
  - [x] 5.1 Change `router.include_router(eval.router, prefix="/eval", ...)` to `router.include_router(eval.router, prefix="/agents", tags=["eval"])` — this makes eval endpoints resolve to `/v1/agents/{agent_id}/eval/...` matching all other agent-scoped routes

- [x] Task 6: Register `EvalDataset` in Beanie init in `app/main.py`
  - [x] 6.1 Add `from app.models.eval import EvalDataset` import
  - [x] 6.2 Add `EvalDataset` to `document_models` list in `init_beanie(...)` call
  - [x] 6.3 NOTE: Story 6.2 will also add `EvalExperiment` here — leave a comment `# EvalExperiment added in Story 6.2`

- [x] Task 7: Add eval error codes to `app/core/errors.py`
  - [x] 7.1 Add `EVAL_DATASET_NOT_FOUND = "EVAL_DATASET_NOT_FOUND"` to `ErrorCode` enum
  - [x] 7.2 Add `EVAL_NO_DATASET = "EVAL_NO_DATASET"` to `ErrorCode` enum (used in Story 6.2 when eval run triggered but no dataset exists)
  - [x] 7.3 Add `EvalDatasetNotFoundError(TrueRAGError)` class with `http_status=404`, `code=ErrorCode.EVAL_DATASET_NOT_FOUND`
  - [x] 7.4 Add `EvalNoDatasetError(TrueRAGError)` class with `http_status=422`, `code=ErrorCode.EVAL_NO_DATASET`

- [x] Task 8: Write tests
  - [x] 8.1 `tests/api/v1/test_eval.py` (new file):
    - `test_create_eval_dataset_returns_201` — mock `eval_service.create_or_replace_dataset`, assert 201 + response fields
    - `test_create_eval_dataset_cross_tenant_returns_403` — mock service raises `ForbiddenError`, assert 403
    - `test_create_eval_dataset_agent_not_found_returns_404` — mock service raises `AgentNotFoundError`, assert 404
    - `test_create_eval_dataset_empty_questions_returns_422` — send `questions: []`, assert 422 (Pydantic validation)
  - [x] 8.2 `tests/services/test_eval_service.py` (new file):
    - `test_create_or_replace_dataset_new_agent` — mock DAO, assert insert_one called, semantic_cache.invalidate called
    - `test_create_or_replace_dataset_replaces_existing` — mock DAO returns existing doc, assert delete called before insert
    - `test_create_or_replace_dataset_forbidden` — mock agent_service.get_agent raises ForbiddenError, assert propagated

- [x] Task 9: Regression gate — `uv run pytest --tb=short -q` — all existing tests must pass

## Dev Notes

### CRITICAL: Router Prefix Bug Fix (Task 5)

`app/api/v1/__init__.py` currently registers the eval router with `prefix="/eval"`, which would produce routes like `/v1/eval/...` — wrong. All eval endpoints must be `/v1/agents/{agent_id}/eval/...`. Fix:

```python
# BEFORE (wrong — creates /v1/eval/... routes)
router.include_router(eval.router, prefix="/eval", tags=["eval"])

# AFTER (correct — creates /v1/agents/{agent_id}/eval/... routes)
router.include_router(eval.router, prefix="/agents", tags=["eval"])
```

This matches the pattern of `documents.router` and `query.router` which both use `prefix="/agents"`.

### EvalDataset Beanie Document Pattern

Follow the exact same pattern as `IngestionJob` in `app/models/ingestion_job.py`:

```python
from datetime import UTC, datetime
from beanie import Document
from pydantic import BaseModel, Field

class EvalQuestion(BaseModel):
    question: str
    expected_answer: str

class EvalDataset(Document):
    agent_id: str
    tenant_id: str
    questions: list[EvalQuestion]
    created_at: datetime

    class Settings:
        name = "eval_datasets"
```

### semantic_cache.invalidate Pattern

Story 1.9 created `app/utils/semantic_cache.py` as a no-op stub. Import pattern:

```python
from app.utils import semantic_cache
# ...
await semantic_cache.invalidate(agent_id)
```

Call this on EVERY dataset write (create or replace) — not conditionally. The stub is a silent no-op and the Epic 8 real implementation shares the same signature. No `if enabled:` guard.

### Beanie Registration in main.py

`init_beanie` requires ALL document models at startup. Pattern from existing code:

```python
await init_beanie(
    database=db,
    document_models=[TenantDocument, AgentDocument, DocumentRecord, IngestionJob, EvalDataset],
    # EvalExperiment added in Story 6.2
)
```

### Authorization Pattern (reuse agent_service.get_agent)

Do NOT implement cross-tenant checks manually in eval_service.py. `agent_service.get_agent(agent_id, tenant_id)` already handles:
- `AgentNotFoundError` (404) if agent doesn't exist
- `ForbiddenError` (403) if agent belongs to different tenant

Call this at the start of every eval service function.

### Structured Logging Pattern

```python
logger.info(
    "eval_dataset_replaced",
    extra={
        "operation": "eval_dataset_replace",
        "extra_data": {"agent_id": agent_id, "tenant_id": tenant_id, "question_count": len(questions)},
    },
)
```

### Route Handler Pattern

```python
from fastapi import APIRouter, Request
from app.models.eval import EvalDatasetCreateRequest, EvalDatasetCreateResponse
from app.services import eval_service

router = APIRouter()

@router.post("/{agent_id}/eval", status_code=201, response_model=EvalDatasetCreateResponse)
async def create_eval_dataset(
    agent_id: str,
    body: EvalDatasetCreateRequest,
    request: Request,
) -> EvalDatasetCreateResponse:
    tenant_id: str = request.state.tenant_id
    dataset = await eval_service.create_or_replace_dataset(
        agent_id=agent_id,
        tenant_id=tenant_id,
        questions=body.questions,
    )
    return EvalDatasetCreateResponse(
        dataset_id=str(dataset.id),
        agent_id=dataset.agent_id,
        tenant_id=dataset.tenant_id,
        question_count=len(dataset.questions),
        created_at=dataset.created_at,
    )
```

### Files to Create
- `app/models/eval.py`
- `app/db/dao/eval_dataset_dao.py`
- `app/services/eval_service.py`
- `tests/api/v1/test_eval.py`
- `tests/services/test_eval_service.py`

### Files to Modify
- `app/api/v1/eval.py` — add POST endpoint
- `app/api/v1/__init__.py` — fix eval router prefix (CRITICAL)
- `app/main.py` — add EvalDataset to init_beanie
- `app/core/errors.py` — add EVAL_DATASET_NOT_FOUND, EVAL_NO_DATASET

### References
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Architecture] — `eval_datasets` collection schema
- [Source: _bmad-output/planning-artifacts/architecture.md#Structure Patterns] — DAO layer pattern, BaseDAO usage
- [Source: _bmad-output/planning-artifacts/epics.md#Story 6.1] — acceptance criteria
- [Source: app/db/dao/agent_dao.py] — DAO singleton pattern
- [Source: app/services/agent_service.py#get_agent] — cross-tenant authorization pattern
- [Source: app/utils/semantic_cache.py] — no-op stub, call pattern

## Dev Agent Record

### Agent Model Used

- GPT-5 Codex

### Debug Log References

- Implemented eval dataset model/DAO/service/API route.
- Applied router prefix fix from `/v1/eval/...` to `/v1/agents/...`.
- Added eval error codes and exceptions.
- Added API/service tests for dataset creation and replacement behavior.
### Completion Notes List

- Implemented `POST /v1/agents/{agent_id}/eval` with 201 response model.
- Added dataset replace workflow (delete old + insert new) with semantic cache invalidation.
- Registered eval models in Beanie startup model list.
### File List

- app/models/eval.py
- app/db/dao/eval_dataset_dao.py
- app/services/eval_service.py
- app/api/v1/eval.py
- app/api/v1/__init__.py
- app/main.py
- app/core/errors.py
- tests/api/v1/test_eval.py
- tests/services/test_eval_service.py
- tests/conftest.py
## Change Log

- 2026-05-02: Story created (ready-for-dev)
- 2026-05-02: Implemented Story 6.1 tasks, tests, and router prefix fix.
