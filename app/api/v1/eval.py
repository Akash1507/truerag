from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth import get_current_tenant, require_role
from app.models.eval import (
    EvalDatasetCreateRequest,
    EvalDatasetCreateResponse,
    EvalDatasetGetResponse,
    EvalHistoryResponse,
    EvalRunResponse,
    EvalRunAcceptedResponse,
)
from app.models.tenant import TenantDocument
from app.services.eval_service import eval_service

router = APIRouter()


@router.get("/{agent_id}/eval", response_model=EvalDatasetGetResponse)
async def get_eval_dataset(
    agent_id: str,
    caller: TenantDocument = Depends(get_current_tenant),  
) -> EvalDatasetGetResponse:
    return await eval_service.get_dataset(agent_id=agent_id, tenant_id=caller.tenant_id)


@router.post("/{agent_id}/eval", status_code=201, response_model=EvalDatasetCreateResponse)
async def create_eval_dataset(
    agent_id: str,
    body: EvalDatasetCreateRequest,
    caller: TenantDocument = Depends(require_role("admin", "agent_owner")),  
) -> EvalDatasetCreateResponse:
    return await eval_service.create_eval_dataset(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        questions=body.questions,
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
    caller: TenantDocument = Depends(require_role("admin", "agent_owner")),  
) -> EvalRunResponse | JSONResponse:
    # CI-CD: read faithfulness from response, fail pipeline if < threshold.
    request.state.background_tasks = background_tasks
    result = await eval_service.run_eval(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        background_tasks=background_tasks,
    )
    if isinstance(result, EvalRunAcceptedResponse):
        return JSONResponse(status_code=202, content=result.model_dump())
    return result


@router.get("/{agent_id}/eval/history", response_model=EvalHistoryResponse)
async def get_eval_history(
    agent_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),  
) -> EvalHistoryResponse:
    return await eval_service.get_eval_history(
        agent_id=agent_id,
        tenant_id=caller.tenant_id,
        cursor=cursor,
        limit=limit,
    )
