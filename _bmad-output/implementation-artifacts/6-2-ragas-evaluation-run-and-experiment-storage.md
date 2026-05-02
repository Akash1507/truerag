# Story 6.2: RAGAS Evaluation Run & Experiment Storage

Status: done

## Story

As a Tenant Developer,
I want to trigger a RAGAS evaluation run against my agent's golden dataset and have the full result stored as an experiment,
so that I can measure faithfulness, answer relevance, context recall, and context precision against a known baseline (FR40, FR41).

## Acceptance Criteria

**AC1 — Synchronous eval (≤20 questions): HTTP 200 with full scores**
Given `POST /v1/agents/{agent_id}/eval/run` for an agent with a golden dataset of 20 or fewer questions
When the request is processed
Then RAGAS evaluation runs synchronously; scores for faithfulness, answer_relevancy, context_recall, and context_precision are computed; HTTP 200 is returned with the full experiment record including all scores

**AC2 — Async eval (>20 questions): HTTP 202 with run_id**
Given `POST /v1/agents/{agent_id}/eval/run` for an agent with a golden dataset exceeding 20 questions
When the request is processed
Then HTTP 202 Accepted is returned immediately with a `run_id`; the evaluation runs as a FastAPI background task; the caller polls `GET /v1/agents/{agent_id}/eval/history` for the completed result

**AC3 — RAGAS called via run_in_executor (non-blocking)**
Given RAGAS evaluation executes (synchronous or background path)
When `eval_service.py` calls the RAGAS evaluate function
Then `asyncio.get_event_loop().run_in_executor(None, fn)` is used to avoid blocking the async event loop

**AC4 — Experiment record written to MongoDB**
Given the evaluation run completes
When results are stored
Then an experiment record is written to `eval_experiments` with: `agent_id`, `tenant_id`, `run_id` (UUID), `config_snapshot` (full agent config dict), `ragas_scores` (faithfulness, answer_relevancy, context_recall, context_precision), `baseline_delta` (faithfulness delta from previous run, 0.0 if first run), `triggered_alert` (False — set by Story 6.3), `created_at`

**AC5 — No golden dataset: HTTP 422**
Given `POST /v1/agents/{agent_id}/eval/run` for an agent with no golden dataset
When the request is processed
Then HTTP 422 Unprocessable Entity is returned with `error.code == "EVAL_NO_DATASET"`; no eval run occurs

## Tasks / Subtasks

- [x] Task 1: Add `EvalExperiment`, `RAGASScores`, response schemas to `app/models/eval.py`
  - [x] 1.1 `RAGASScores(BaseModel)`: `faithfulness: float`, `answer_relevancy: float`, `context_recall: float`, `context_precision: float`
  - [x] 1.2 `EvalExperiment(Document)`: Beanie document; fields: `agent_id: str`, `tenant_id: str`, `run_id: str`, `config_snapshot: dict`, `ragas_scores: RAGASScores`, `baseline_delta: float`, `triggered_alert: bool`, `created_at: datetime`; `class Settings: name = "eval_experiments"`
  - [x] 1.3 `EvalRunResponse(BaseModel)`: `run_id: str`, `agent_id: str`, `tenant_id: str`, `ragas_scores: RAGASScores`, `baseline_delta: float`, `triggered_alert: bool`, `created_at: datetime` (synchronous 200 response)
  - [x] 1.4 `EvalRunAcceptedResponse(BaseModel)`: `run_id: str`, `agent_id: str`, `status: str = "running"` (async 202 response)

- [x] Task 2: Create `app/db/dao/eval_experiment_dao.py`
  - [x] 2.1 `EvalExperimentDAO(BaseDAO[EvalExperiment])` following same singleton pattern as `eval_dataset_dao.py`
  - [x] 2.2 `eval_experiment_dao = EvalExperimentDAO()` module-level singleton

- [x] Task 3: Add `ragas` and `datasets` to `requirements.txt`
  - [x] 3.1 Add `ragas>=0.1.0,<0.2.0` — use 0.1.x which has the stable `evaluate()` + HuggingFace `Dataset` API (see Dev Notes for exact API)
  - [x] 3.2 Add `datasets>=2.14.0,<3.0.0` — required by RAGAS 0.1.x for `Dataset.from_dict()`
  - [x] 3.3 Run `uv pip install -r requirements.txt` to update the environment

- [x] Task 4: Expand `app/services/eval_service.py` — add eval run orchestration
  - [x] 4.1 Add `_collect_eval_data(agent, dataset) -> list[dict]` async helper:
    - For each question in dataset.questions: call `run_query_pipeline(query=q.question, top_k=agent.top_k, agent=agent)` 
    - Collect `{"question": q.question, "answer": response.answer, "contexts": [c.chunk_text for c in response.citations], "ground_truths": [q.expected_answer]}`
    - Return list of these dicts
  - [x] 4.2 Add `_run_ragas_sync(eval_data: list[dict]) -> RAGASScores` sync function (runs in executor):
    - Import `from datasets import Dataset; from ragas import evaluate; from ragas.metrics import faithfulness, answer_relevancy, context_recall, context_precision`
    - `dataset = Dataset.from_list(eval_data)`
    - `result = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_recall, context_precision])`
    - Return `RAGASScores(faithfulness=float(result["faithfulness"]), answer_relevancy=float(result["answer_relevancy"]), context_recall=float(result["context_recall"]), context_precision=float(result["context_precision"]))`
  - [x] 4.3 Add `_get_baseline_delta(agent_id: str, current_faithfulness: float) -> float` async helper:
    - Fetch most recent prior experiment: `await eval_experiment_dao.find({"agent_id": agent_id}, sort=[("created_at", -1)], limit=1)`
    - Return `current_faithfulness - prior.ragas_scores.faithfulness` if prior exists, else `0.0`
  - [x] 4.4 Add `run_evaluation(agent_id: str, tenant_id: str) -> EvalExperiment` async function:
    - `agent = await agent_service.get_agent(agent_id, tenant_id)` — handles 403/404
    - `dataset = await eval_dataset_dao.find_one({"agent_id": agent_id})` — if None: raise `EvalNoDatasetError`
    - `eval_data = await _collect_eval_data(agent, dataset)`
    - `loop = asyncio.get_event_loop()`
    - `ragas_scores = await loop.run_in_executor(None, _run_ragas_sync, eval_data)` — non-blocking
    - `baseline_delta = await _get_baseline_delta(agent_id, ragas_scores.faithfulness)`
    - Build `run_id = str(uuid.uuid4())`
    - Build `config_snapshot = agent.model_dump()` (full agent config as dict; convert ObjectIds to str)
    - Create `EvalExperiment(...)` with `triggered_alert=False` (Story 6.3 sets this)
    - `await eval_experiment_dao.insert_one(experiment)`
    - Log structured: `logger.info("eval_run_complete", extra={"operation": "eval_run", "extra_data": {"agent_id": agent_id, "run_id": run_id, "faithfulness": ragas_scores.faithfulness}})`
    - Return experiment

- [x] Task 5: Add `POST /v1/agents/{agent_id}/eval/run` to `app/api/v1/eval.py`
  - [x] 5.1 Synchronous path (≤20 questions): call `await eval_service.run_evaluation(...)`, return 200 with `EvalRunResponse`
  - [x] 5.2 Check question count: `dataset = await eval_service.get_dataset(agent_id, tenant_id)` then `len(dataset.questions) > 20`
  - [x] 5.3 Async path (>20 questions): `run_id = str(uuid.uuid4())`, add `background_tasks.add_task(eval_service.run_evaluation, agent_id, tenant_id)`, return 202 with `EvalRunAcceptedResponse(run_id=run_id, agent_id=agent_id)`
  - [x] 5.4 Add `get_dataset(agent_id: str, tenant_id: str) -> EvalDataset` helper to eval_service (for route to check question count before deciding sync/async path)

- [x] Task 6: Register `EvalExperiment` in Beanie in `app/main.py`
  - [x] 6.1 Add `from app.models.eval import EvalDataset, EvalExperiment`
  - [x] 6.2 Add both `EvalDataset` and `EvalExperiment` to `document_models` list

- [x] Task 7: Write tests
  - [x] 7.1 Add to `tests/api/v1/test_eval.py`:
    - `test_eval_run_sync_returns_200` — ≤20 questions, mock service, assert 200 + ragas_scores present
    - `test_eval_run_async_returns_202` — >20 questions, assert 202 + run_id present
    - `test_eval_run_no_dataset_returns_422` — mock raises EvalNoDatasetError, assert 422
  - [x] 7.2 Add to `tests/services/test_eval_service.py`:
    - `test_run_evaluation_calls_ragas_in_executor` — mock `run_in_executor`, verify called with `_run_ragas_sync`
    - `test_run_evaluation_stores_experiment` — mock all deps, assert `eval_experiment_dao.insert_one` called with correct schema
    - `test_run_evaluation_baseline_delta_first_run` — no prior experiments, assert `baseline_delta == 0.0`
    - `test_run_evaluation_baseline_delta_regression` — prior experiment with faithfulness=0.8, new=0.6, assert delta=-0.2
    - `test_run_evaluation_no_dataset_raises` — no dataset, assert EvalNoDatasetError

- [x] Task 8: Regression gate — `uv run pytest --tb=short -q` — all previously passing tests must still pass

## Dev Notes

### RAGAS API (version 0.1.x)

Pin `ragas>=0.1.0,<0.2.0`. The 0.1.x API uses HuggingFace `datasets` directly:

```python
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_recall, context_precision

def _run_ragas_sync(eval_data: list[dict]) -> RAGASScores:
    dataset = Dataset.from_list(eval_data)
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_recall, context_precision],
    )
    return RAGASScores(
        faithfulness=float(result["faithfulness"]),
        answer_relevancy=float(result["answer_relevancy"]),
        context_recall=float(result["context_recall"]),
        context_precision=float(result["context_precision"]),
    )
```

`eval_data` list shape (required by RAGAS):
```python
[
    {
        "question": "What is X?",
        "answer": "X is ...",                     # from run_query_pipeline
        "contexts": ["chunk text 1", "chunk 2"],  # from response.citations[].chunk_text
        "ground_truths": ["expected answer"],     # from dataset.questions[].expected_answer
    },
    ...
]
```

**Note:** RAGAS 0.1.x uses OpenAI by default for LLM-backed metrics (faithfulness, answer_relevancy). The `openai_api_key_secret_name` in Settings already references the OpenAI key in Secrets Manager. The RAGAS library reads `OPENAI_API_KEY` from the environment. Before running eval, ensure `OPENAI_API_KEY` is set (via `app/utils/secrets.py` at operation time if needed).

### run_in_executor Pattern

RAGAS `evaluate()` is synchronous and CPU/IO-bound. Must not block the async event loop:

```python
import asyncio

async def run_evaluation(agent_id: str, tenant_id: str) -> EvalExperiment:
    # ... collect eval_data async ...
    loop = asyncio.get_event_loop()
    ragas_scores = await loop.run_in_executor(None, _run_ragas_sync, eval_data)
    # ...
```

`run_in_executor(None, fn, *args)` uses the default ThreadPoolExecutor. The function `_run_ragas_sync` must be defined at module level (not a lambda) so it can be pickled.

### config_snapshot Serialization

`agent.model_dump()` returns a dict with Pydantic types. To store in MongoDB cleanly:

```python
import json
config_snapshot = json.loads(agent.model_dump_json())
```

This converts datetime fields to ISO strings and ObjectIds to strings, making it safe for MongoDB storage as a plain dict.

### Background Task for >20 Questions

The route layer checks question count and branches:

```python
@router.post("/{agent_id}/eval/run")
async def trigger_eval_run(
    agent_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> EvalRunResponse | EvalRunAcceptedResponse:
    tenant_id: str = request.state.tenant_id
    dataset = await eval_service.get_dataset(agent_id, tenant_id)
    
    if len(dataset.questions) <= 20:
        experiment = await eval_service.run_evaluation(agent_id, tenant_id)
        return EvalRunResponse(...)  # HTTP 200
    else:
        run_id = str(uuid.uuid4())
        background_tasks.add_task(eval_service.run_evaluation, agent_id, tenant_id)
        return JSONResponse(
            status_code=202,
            content=EvalRunAcceptedResponse(run_id=run_id, agent_id=agent_id).model_dump(),
        )
```

### EvalExperiment config_snapshot Field

`config_snapshot` is a `dict` in MongoDB (not typed). Store as:
```python
"config_snapshot": json.loads(agent.model_dump_json())
```

This ensures datetimes serialize properly and the snapshot is human-readable in MongoDB.

### baseline_delta Calculation

Previous experiment query — must be most recent for the agent, before the current run:

```python
async def _get_baseline_delta(agent_id: str, current_faithfulness: float) -> float:
    prior = await eval_experiment_dao.find(
        {"agent_id": agent_id},
        sort=[("created_at", -1)],
        limit=1,
    )
    if not prior:
        return 0.0
    return round(current_faithfulness - prior[0].ragas_scores.faithfulness, 4)
```

### Files to Create
- `app/db/dao/eval_experiment_dao.py`

### Files to Modify
- `app/models/eval.py` — add RAGASScores, EvalExperiment, EvalRunResponse, EvalRunAcceptedResponse
- `app/services/eval_service.py` — add run_evaluation, _collect_eval_data, _run_ragas_sync, get_dataset
- `app/api/v1/eval.py` — add POST /{agent_id}/eval/run endpoint
- `app/main.py` — add EvalExperiment to init_beanie (replace Story 6.1 comment)
- `requirements.txt` — add ragas and datasets

### References
- [Source: _bmad-output/planning-artifacts/epics.md#Story 6.2] — acceptance criteria
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Architecture] — eval_experiments schema
- [Source: app/services/query_service.py] — run_query_pipeline call pattern
- [Source: app/models/query.py#Citation] — chunk_text field for RAGAS contexts
- [Source: app/services/audit_service.py] — aioboto3 session pattern (model for eval_service)

## Dev Agent Record

### Agent Model Used

- GPT-5 Codex

### Debug Log References

- Added eval experiment document and DAO.
- Added sync/async eval-run API flow and service orchestration.
- Added `run_in_executor` path and baseline delta calculation.
- Added API/service tests for eval run behaviors.
### Completion Notes List

- Implemented `POST /v1/agents/{agent_id}/eval/run` with sync 200 and async 202 paths.
- Added `EvalExperiment` persistence with config snapshot and baseline delta.
- Added `ragas` and `datasets` requirement pins.
### File List

- app/models/eval.py
- app/db/dao/eval_experiment_dao.py
- app/services/eval_service.py
- app/api/v1/eval.py
- app/main.py
- requirements.txt
- tests/api/v1/test_eval.py
- tests/services/test_eval_service.py
## Change Log

- 2026-05-02: Story created (ready-for-dev)
- 2026-05-02: Implemented Story 6.2 tasks and eval run tests.
