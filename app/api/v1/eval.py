import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth import get_current_tenant
from app.core.errors import InvalidCursorError
from app.models.eval import (
    EvalDatasetCreateRequest,
    EvalDatasetCreateResponse,
    EvalExperimentSummary,
    EvalHistoryResponse,
    EvalRunAcceptedResponse,
    EvalRunResponse,
)
from app.models.tenant import TenantDocument
from app.services import eval_service

router = APIRouter()


@router.post("/{agent_id}/eval", status_code=201, response_model=EvalDatasetCreateResponse)
async def create_eval_dataset(
    agent_id: str,
    body: EvalDatasetCreateRequest,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> EvalDatasetCreateResponse:
    dataset = await eval_service.create_or_replace_dataset(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        questions=body.questions,
    )
    return EvalDatasetCreateResponse(
        dataset_id=str(dataset.id),
        agent_id=dataset.agent_id,
        tenant_id=dataset.tenant_id,
        question_count=len(dataset.questions),
        created_at=dataset.created_at,
    )


@router.post(
    "/{agent_id}/eval/run",
    status_code=200,
    response_model=EvalRunResponse | EvalRunAcceptedResponse,
)
async def run_eval(
    agent_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> EvalRunResponse | JSONResponse:
    # CI-CD: read faithfulness from response, fail pipeline if < threshold. No special mode needed.
    request.state.background_tasks = background_tasks
    dataset = await eval_service.get_dataset(agent_id, caller.tenant_id)
    if len(dataset.questions) > 20:
        run_id = str(uuid.uuid4())
        background_tasks.add_task(eval_service.run_evaluation, agent_id, caller.tenant_id)
        return JSONResponse(
            status_code=202,
            content=EvalRunAcceptedResponse(run_id=run_id, agent_id=agent_id).model_dump(),
        )

    experiment = await eval_service.run_evaluation(agent_id, caller.tenant_id)
    return EvalRunResponse(
        run_id=experiment.run_id,
        agent_id=experiment.agent_id,
        tenant_id=experiment.tenant_id,
        ragas_scores=experiment.ragas_scores,
        baseline_delta=experiment.baseline_delta,
        triggered_alert=experiment.triggered_alert,
        regression_reason=getattr(experiment, "regression_reason", None),
        created_at=experiment.created_at,
    )


@router.get("/{agent_id}/eval/history", response_model=EvalHistoryResponse)
async def get_eval_history(
    agent_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),  # noqa: B008
) -> EvalHistoryResponse:
    try:
        experiments, next_cursor = await eval_service.list_experiments(
            agent_id=agent_id,
            tenant_id=caller.tenant_id,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc

    return EvalHistoryResponse(
        items=[
            EvalExperimentSummary(
                run_id=e.run_id,
                ragas_scores=e.ragas_scores,
                config_snapshot=e.config_snapshot,
                baseline_delta=e.baseline_delta,
                triggered_alert=e.triggered_alert,
                regression_reason=e.regression_reason,
                created_at=e.created_at,
            )
            for e in experiments
        ],
        next_cursor=next_cursor,
    )
