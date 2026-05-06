import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import AgentNotFoundError, EvalNoDatasetError, ForbiddenError
from app.models.eval import (
    EvalDatasetCreateResponse,
    EvalExperimentSummary,
    EvalHistoryResponse,
    EvalRunAcceptedResponse,
    EvalRunResponse,
    RAGASScores,
)
from app.models.tenant import TenantDocument
from app.services.eval_service import eval_service


def _tenant(api_key: str = "key") -> TenantDocument:
    return TenantDocument(
        tenant_id="tenant-1",
        name="tenant-1",
        api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_create_eval_dataset_returns_201(client) -> None:  # type: ignore[no-untyped-def]
    dataset = EvalDatasetCreateResponse(
        dataset_id="dataset-1",
        agent_id="agent-1",
        tenant_id="tenant-1",
        question_count=1,
        created_at=datetime.now(UTC),
    )
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "create_eval_dataset",
        AsyncMock(return_value=dataset),
    ):
        response = await client.post(
            "/v1/agents/agent-1/eval",
            json={"questions": [{"question": "q", "expected_answer": "a"}]},
            headers={"X-API-Key": "key"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["dataset_id"] == "dataset-1"
    assert body["agent_id"] == "agent-1"
    assert body["tenant_id"] == "tenant-1"
    assert body["question_count"] == 1


@pytest.mark.asyncio
async def test_create_eval_dataset_cross_tenant_returns_403(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "create_eval_dataset",
        AsyncMock(side_effect=ForbiddenError("forbidden")),
    ):
        response = await client.post(
            "/v1/agents/agent-1/eval",
            json={"questions": [{"question": "q", "expected_answer": "a"}]},
            headers={"X-API-Key": "key"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_eval_dataset_agent_not_found_returns_404(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "create_eval_dataset",
        AsyncMock(side_effect=AgentNotFoundError("not found")),
    ):
        response = await client.post(
            "/v1/agents/agent-1/eval",
            json={"questions": [{"question": "q", "expected_answer": "a"}]},
            headers={"X-API-Key": "key"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_eval_dataset_empty_questions_returns_422(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())):
        response = await client.post(
            "/v1/agents/agent-1/eval",
            json={"questions": []},
            headers={"X-API-Key": "key"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_eval_run_sync_returns_200(client) -> None:  # type: ignore[no-untyped-def]
    run_response = EvalRunResponse(
        run_id="run-1",
        agent_id="agent-1",
        tenant_id="tenant-1",
        ragas_scores=RAGASScores(
            faithfulness=0.9,
            answer_relevancy=0.8,
            context_recall=0.7,
            context_precision=0.6,
        ),
        baseline_delta=0.1,
        triggered_alert=False,
        regression_reason=None,
        created_at=datetime.now(UTC),
    )
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "run_eval",
        AsyncMock(return_value=run_response),
    ):
        response = await client.post("/v1/agents/agent-1/eval/run", headers={"X-API-Key": "key"})

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run-1"
    assert set(body["ragas_scores"].keys()) == {
        "faithfulness",
        "answer_relevancy",
        "context_recall",
        "context_precision",
    }


@pytest.mark.asyncio
async def test_eval_run_async_returns_202(client) -> None:  # type: ignore[no-untyped-def]
    accepted = EvalRunAcceptedResponse(run_id="run-202", agent_id="agent-1")
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "run_eval",
        AsyncMock(return_value=accepted),
    ):
        response = await client.post("/v1/agents/agent-1/eval/run", headers={"X-API-Key": "key"})

    assert response.status_code == 202
    body = response.json()
    assert body["agent_id"] == "agent-1"
    assert body["status"] == "running"
    assert body["run_id"]


@pytest.mark.asyncio
async def test_eval_run_no_dataset_returns_422(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "run_eval",
        AsyncMock(side_effect=EvalNoDatasetError("no dataset")),
    ):
        response = await client.post("/v1/agents/agent-1/eval/run", headers={"X-API-Key": "key"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EVAL_NO_DATASET"


@pytest.mark.asyncio
async def test_eval_history_returns_paginated_list(client) -> None:  # type: ignore[no-untyped-def]
    history = EvalHistoryResponse(
        items=[
            EvalExperimentSummary(
            run_id=f"run-{i}",
            ragas_scores=RAGASScores(
                faithfulness=0.9 - (i * 0.01),
                answer_relevancy=0.8,
                context_recall=0.7,
                context_precision=0.6,
            ),
            config_snapshot={"k": i},
            baseline_delta=0.1,
            triggered_alert=False,
            regression_reason=None,
            created_at=datetime.now(UTC),
        )
        for i in range(3)
        ],
        next_cursor=None,
    )
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "get_eval_history",
        AsyncMock(return_value=history),
    ):
        response = await client.get("/v1/agents/agent-1/eval/history", headers={"X-API-Key": "key"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["run_id"] == "run-0"
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_eval_history_cursor_pagination(client) -> None:  # type: ignore[no-untyped-def]
    first_page = EvalHistoryResponse(
        items=[
            EvalExperimentSummary(
            run_id=f"run-{i}",
            ragas_scores=RAGASScores(
                faithfulness=0.9, answer_relevancy=0.8, context_recall=0.7, context_precision=0.6
            ),
            config_snapshot={},
            baseline_delta=0.0,
            triggered_alert=False,
            regression_reason=None,
            created_at=datetime.now(UTC),
        )
        for i in range(20)
        ],
        next_cursor="cursor-1",
    )
    second_page = EvalHistoryResponse(
        items=[
            EvalExperimentSummary(
            run_id="run-last",
            ragas_scores=RAGASScores(
                faithfulness=0.8, answer_relevancy=0.8, context_recall=0.7, context_precision=0.6
            ),
            config_snapshot={},
            baseline_delta=-0.1,
            triggered_alert=True,
            regression_reason="faithfulness below threshold",
            created_at=datetime.now(UTC),
        )
        ],
        next_cursor=None,
    )
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "get_eval_history",
        AsyncMock(side_effect=[first_page, second_page]),
    ):
        response1 = await client.get(
            "/v1/agents/agent-1/eval/history?limit=20", headers={"X-API-Key": "key"}
        )
        response2 = await client.get(
            "/v1/agents/agent-1/eval/history?limit=20&cursor=cursor-1",
            headers={"X-API-Key": "key"},
        )
    assert response1.status_code == 200
    assert len(response1.json()["items"]) == 20
    assert response1.json()["next_cursor"] == "cursor-1"
    assert response2.status_code == 200
    assert len(response2.json()["items"]) == 1
    assert response2.json()["next_cursor"] is None


@pytest.mark.asyncio
async def test_eval_history_cross_tenant_returns_403(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "get_eval_history",
        AsyncMock(side_effect=ForbiddenError("forbidden")),
    ):
        response = await client.get("/v1/agents/agent-1/eval/history", headers={"X-API-Key": "key"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_eval_history_empty_returns_empty_list(client) -> None:  # type: ignore[no-untyped-def]
    with patch("app.core.auth.tenant_dao.find_one", AsyncMock(return_value=_tenant())), patch.object(
        eval_service,
        "get_eval_history",
        AsyncMock(return_value=EvalHistoryResponse(items=[], next_cursor=None)),
    ):
        response = await client.get("/v1/agents/agent-1/eval/history", headers={"X-API-Key": "key"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["next_cursor"] is None
