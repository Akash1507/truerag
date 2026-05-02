# Story 6.3: Regression Detection & Alert

Status: done

## Story

As a Platform Admin,
I want automatic regression alerts pushed when an agent's RAGAS faithfulness score drops below its configured threshold,
so that quality degradation is surfaced immediately without manual monitoring (FR42, NFR4).

## Acceptance Criteria

**AC1 — Regression triggers CloudWatch metric + triggered_alert flag**
Given an evaluation run completes and the faithfulness score is below the agent's configured `faithfulness_threshold` (default 0.6)
When `eval_service.py` processes the result
Then a custom metric `FaithfulnessRegression` is written to CloudWatch namespace `TrueRAG/EvalQuality` with dimensions `tenant_id` and `agent_id`; the experiment record has `triggered_alert: true`

**AC2 — No metric write when score is above threshold**
Given an evaluation run completes with faithfulness score at or above the agent's threshold
When the result is processed
Then no CloudWatch metric write occurs; the experiment record has `triggered_alert: false`

**AC3 — ADR documents v1 alerting mechanism**
Given the regression alert mechanism is implemented
When documented in `docs/adrs/`
Then the ADR explicitly states that v1 delivers email notification via Terraform-configured CloudWatch alarm + SNS; Slack/webhook push is deferred to v2

## Tasks / Subtasks

- [x] Task 1: Add `faithfulness_threshold` to `AgentDocument` and request/response models in `app/models/agent.py`
  - [x] 1.1 Add `faithfulness_threshold: float = Field(default=0.6, ge=0.0, le=1.0)` to `AgentDocument`
  - [x] 1.2 Add `faithfulness_threshold: float = Field(default=0.6, ge=0.0, le=1.0)` to `AgentCreateRequest`
  - [x] 1.3 Add `faithfulness_threshold: float` to `AgentCreateResponse` and `AgentUpdateResponse`
  - [x] 1.4 Add `faithfulness_threshold: float | None = Field(default=None, ge=0.0, le=1.0)` to `AgentConfigUpdateRequest` (optional update field)

- [x] Task 2: Expand `app/services/eval_service.py` — wire regression check into `run_evaluation`
  - [x] 2.1 Add `_default_session: aioboto3.Session = aioboto3.Session()` module-level (same pattern as `audit_service.py`)
  - [x] 2.2 Add `_write_regression_metric(tenant_id, agent_id, faithfulness, session) -> None` async helper:
    - Open `session.client("cloudwatch", region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url)` via async context manager
    - Call `put_metric_data(Namespace="TrueRAG/EvalQuality", MetricData=[{...}])` — see Dev Notes for exact shape
    - Wrap in try/except; log warning on failure (non-fatal — do not raise; regression metric write must never block experiment storage)
  - [x] 2.3 In `run_evaluation`, after computing `ragas_scores`:
    - `triggered_alert = ragas_scores.faithfulness < agent.faithfulness_threshold`
    - If `triggered_alert`: call `await _write_regression_metric(tenant_id, agent_id, ragas_scores.faithfulness, _default_session)`
  - [x] 2.4 Pass `triggered_alert` when constructing `EvalExperiment` (replaces the hardcoded `False` from Story 6.2)

- [x] Task 3: Write ADR `docs/adrs/adr-011-regression-detection-cloudwatch-sns.md`
  - [x] 3.1 Sections: Title, Status (Accepted), Context, Decision, Consequences
  - [x] 3.2 Must state: v1 uses CloudWatch custom metric + Terraform-configured alarm + SNS email notification; no direct push (Slack/webhook) in v1
  - [x] 3.3 Must state: CloudWatch metric name `FaithfulnessRegression`, namespace `TrueRAG/EvalQuality`, dimensions `tenant_id` + `agent_id`, unit `None`
  - [x] 3.4 Must state: Slack/webhook push deferred to v2

- [x] Task 4: Write tests
  - [x] 4.1 Add to `tests/services/test_eval_service.py`:
    - `test_regression_writes_cloudwatch_metric` — faithfulness=0.4 < threshold=0.6, mock aioboto3 client, assert `put_metric_data` called with correct namespace + dimensions + value
    - `test_no_regression_no_cloudwatch_write` — faithfulness=0.8 >= threshold=0.6, assert `put_metric_data` NOT called
    - `test_regression_metric_failure_does_not_raise` — `put_metric_data` raises exception, assert `run_evaluation` still returns experiment (non-fatal)
    - `test_experiment_triggered_alert_true_on_regression` — assert stored experiment has `triggered_alert=True`
    - `test_experiment_triggered_alert_false_on_pass` — assert stored experiment has `triggered_alert=False`
  - [x] 4.2 Add to `tests/api/v1/test_agents.py` (or `test_agent_service.py`):
    - `test_create_agent_default_faithfulness_threshold` — create agent without specifying threshold, assert `faithfulness_threshold=0.6` in response
    - `test_create_agent_custom_faithfulness_threshold` — create agent with `faithfulness_threshold=0.75`, assert stored correctly

- [x] Task 5: Regression gate — `uv run pytest --tb=short -q` — all previously passing tests must still pass

## Dev Notes

### faithfulness_threshold Field on AgentDocument

This field is new. All existing `AgentDocument` records in MongoDB without this field will default to `0.6` on read (Pydantic default). No migration needed — Pydantic applies the default when the field is absent. Add to ALL four model classes in `app/models/agent.py`:

```python
# AgentDocument (Beanie document)
faithfulness_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

# AgentCreateRequest
faithfulness_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

# AgentCreateResponse and AgentUpdateResponse
faithfulness_threshold: float

# AgentConfigUpdateRequest (optional partial update)
faithfulness_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
```

### CloudWatch PutMetricData Pattern

Use `aioboto3` async context manager — same session pattern as `audit_service.py`:

```python
import aioboto3  # type: ignore[import-untyped]

_default_session: aioboto3.Session = aioboto3.Session()

async def _write_regression_metric(
    tenant_id: str,
    agent_id: str,
    faithfulness: float,
    session: aioboto3.Session | None = None,
) -> None:
    settings = get_settings()
    _session = session or _default_session
    try:
        async with _session.client(
            "cloudwatch",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as cw:
            await cw.put_metric_data(
                Namespace="TrueRAG/EvalQuality",
                MetricData=[
                    {
                        "MetricName": "FaithfulnessRegression",
                        "Dimensions": [
                            {"Name": "tenant_id", "Value": tenant_id},
                            {"Name": "agent_id", "Value": agent_id},
                        ],
                        "Value": faithfulness,
                        "Unit": "None",
                    }
                ],
            )
    except Exception as exc:
        logger.warning(
            "regression_metric_write_failed",
            extra={
                "operation": "regression_alert",
                "extra_data": {"agent_id": agent_id, "tenant_id": tenant_id, "error": str(exc)},
            },
        )
```

**Non-fatal design:** metric write failure must never propagate. The experiment is already stored; losing the CloudWatch signal is recoverable. Never raise from `_write_regression_metric`.

### run_evaluation Integration Point

Story 6.2 hardcoded `triggered_alert=False`. Replace that with the regression check:

```python
async def run_evaluation(agent_id: str, tenant_id: str) -> EvalExperiment:
    agent = await agent_service.get_agent(agent_id, tenant_id)
    dataset = await eval_dataset_dao.find_one({"agent_id": agent_id})
    if dataset is None:
        raise EvalNoDatasetError()
    
    eval_data = await _collect_eval_data(agent, dataset)
    loop = asyncio.get_event_loop()
    ragas_scores = await loop.run_in_executor(None, _run_ragas_sync, eval_data)
    baseline_delta = await _get_baseline_delta(agent_id, ragas_scores.faithfulness)
    
    # Regression check (Story 6.3 addition)
    triggered_alert = ragas_scores.faithfulness < agent.faithfulness_threshold
    if triggered_alert:
        await _write_regression_metric(tenant_id, agent_id, ragas_scores.faithfulness)
    
    run_id = str(uuid.uuid4())
    config_snapshot = json.loads(agent.model_dump_json())
    experiment = EvalExperiment(
        agent_id=agent_id,
        tenant_id=tenant_id,
        run_id=run_id,
        config_snapshot=config_snapshot,
        ragas_scores=ragas_scores,
        baseline_delta=baseline_delta,
        triggered_alert=triggered_alert,  # ← was False in Story 6.2
        created_at=datetime.now(UTC),
    )
    await eval_experiment_dao.insert_one(experiment)
    return experiment
```

### Terraform CloudWatch Alarm (context only — not implemented in this story)

The Terraform alarm that triggers SNS is configured in `terraform/modules/cloudwatch/`. This story only writes the metric — the alarm and SNS subscription are Epic 10 work. The ADR documents the full v1 alerting chain.

### ADR-011 Location

`docs/adrs/adr-011-regression-detection-cloudwatch-sns.md` — follow same format as other ADRs in the directory. If no existing ADR exists as template, use:

```markdown
# ADR-011: Regression Detection via CloudWatch Metric + SNS Alert

**Status:** Accepted
**Date:** 2026-05-02

## Context
...
## Decision
...
## Consequences
...
```

### Files to Modify
- `app/models/agent.py` — add faithfulness_threshold to all 4 model classes
- `app/services/eval_service.py` — add _write_regression_metric, update run_evaluation

### Files to Create
- `docs/adrs/adr-011-regression-detection-cloudwatch-sns.md`

### References
- [Source: _bmad-output/planning-artifacts/epics.md#Story 6.3] — acceptance criteria
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Boundary] — CloudWatch accessed by eval_service.py via aioboto3
- [Source: app/services/audit_service.py] — aioboto3 session + non-fatal write pattern
- [Source: app/models/agent.py] — all 4 AgentDocument model classes requiring the new field

## Dev Agent Record

### Agent Model Used

GPT-5 Codex (bmad-dev-story workflow)

### Debug Log References
- `uv run --no-sync pytest --tb=short -q tests/services/test_eval_service.py tests/api/v1/test_eval.py tests/api/v1/test_agents_dao.py`
- `uv run --no-sync pytest --tb=short -q`

### Completion Notes List
- Added `faithfulness_threshold` across agent create/update/document/response models and wired through `agent_service`.
- Implemented regression detection in `run_evaluation` with warning log tagging (`operation=regression_alert`) and `triggered_alert`/`regression_reason` persistence.
- Added CloudWatch metric emission helper for `TrueRAG/EvalQuality/FaithfulnessRegression` with non-fatal failure handling.
- Authored ADR-011 documenting v1 CloudWatch + SNS email alerting and v2 Slack/webhook deferral.
- Added service and API tests for threshold defaults/custom values and regression alert behavior.

### File List
- app/models/agent.py
- app/models/eval.py
- app/services/agent_service.py
- app/services/eval_service.py
- app/api/v1/eval.py
- docs/adrs/adr-011-regression-detection-cloudwatch-sns.md
- tests/services/test_eval_service.py
- tests/api/v1/test_eval.py
- tests/api/v1/test_agents_dao.py

## Change Log

- 2026-05-02: Story created (ready-for-dev)
- 2026-05-03: Implemented regression detection, CloudWatch metric alert signal, ADR-011, and test coverage; status moved to review.
