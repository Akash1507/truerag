from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app.core.errors import EvalNoDatasetError, ForbiddenError
from app.models.agent import AgentDocument
from app.models.eval import EvalDataset, EvalExperiment, EvalQuestion, RAGASScores
from app.services import eval_service


def _make_agent() -> AgentDocument:
    return AgentDocument(
        agent_id="agent-1",
        tenant_id="tenant-1",
        name="agent-1",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=5,
        semantic_cache_enabled=False,
        semantic_cache_threshold=None,
        faithfulness_threshold=0.6,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_dataset(question_count: int = 1) -> EvalDataset:
    return EvalDataset(
        agent_id="agent-1",
        tenant_id="tenant-1",
        questions=[EvalQuestion(question=f"q-{i}", expected_answer=f"a-{i}") for i in range(question_count)],
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_create_or_replace_dataset_new_agent() -> None:
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())), patch(
        "app.services.eval_service.eval_dataset_dao.find_one",
        AsyncMock(return_value=None),
    ), patch("app.services.eval_service.eval_dataset_dao.insert_one", AsyncMock()) as mock_insert, patch(
        "app.services.eval_service.semantic_cache.invalidate", AsyncMock()
    ) as mock_invalidate:
        dataset = await eval_service.create_or_replace_dataset(
            "agent-1",
            "tenant-1",
            [EvalQuestion(question="q", expected_answer="a")],
        )

    mock_insert.assert_awaited_once()
    mock_invalidate.assert_awaited_once_with("agent-1")
    assert dataset.agent_id == "agent-1"


@pytest.mark.asyncio
async def test_create_or_replace_dataset_replaces_existing() -> None:
    existing = MagicMock()
    existing.delete = AsyncMock()
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())), patch(
        "app.services.eval_service.eval_dataset_dao.find_one",
        AsyncMock(return_value=existing),
    ), patch("app.services.eval_service.eval_dataset_dao.insert_one", AsyncMock()):
        await eval_service.create_or_replace_dataset(
            "agent-1",
            "tenant-1",
            [EvalQuestion(question="q", expected_answer="a")],
        )

    existing.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_or_replace_dataset_forbidden() -> None:
    with patch(
        "app.services.eval_service.agent_service.get_agent",
        AsyncMock(side_effect=ForbiddenError("forbidden")),
    ), pytest.raises(ForbiddenError):
        await eval_service.create_or_replace_dataset(
            "agent-1",
            "tenant-1",
            [EvalQuestion(question="q", expected_answer="a")],
        )


@pytest.mark.asyncio
async def test_run_evaluation_calls_ragas_in_executor() -> None:
    agent = _make_agent()
    dataset = _make_dataset(1)
    fake_scores = RAGASScores(
        faithfulness=0.8,
        answer_relevancy=0.7,
        context_recall=0.6,
        context_precision=0.5,
    )

    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(return_value=fake_scores)

    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=agent)), patch(
        "app.services.eval_service.eval_dataset_dao.find_one",
        AsyncMock(return_value=dataset),
    ), patch("app.services.eval_service._collect_eval_data", AsyncMock(return_value=[{"question": "q"}])), patch(
        "app.services.eval_service.asyncio.get_event_loop",
        return_value=mock_loop,
    ), patch("app.services.eval_service._get_baseline_delta", AsyncMock(return_value=0.0)), patch(
        "app.services.eval_service.eval_experiment_dao.insert_one",
        AsyncMock(),
    ):
        await eval_service.run_evaluation("agent-1", "tenant-1")

    mock_loop.run_in_executor.assert_awaited_once()
    args = mock_loop.run_in_executor.await_args.args
    assert args[0] is None
    assert args[1] == eval_service._run_ragas_sync


@pytest.mark.asyncio
async def test_run_evaluation_stores_experiment() -> None:
    agent = _make_agent()
    dataset = _make_dataset(1)
    fake_scores = RAGASScores(
        faithfulness=0.8,
        answer_relevancy=0.7,
        context_recall=0.6,
        context_precision=0.5,
    )

    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(return_value=fake_scores)

    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=agent)), patch(
        "app.services.eval_service.eval_dataset_dao.find_one",
        AsyncMock(return_value=dataset),
    ), patch("app.services.eval_service._collect_eval_data", AsyncMock(return_value=[{"question": "q"}])), patch(
        "app.services.eval_service.asyncio.get_event_loop",
        return_value=mock_loop,
    ), patch("app.services.eval_service._get_baseline_delta", AsyncMock(return_value=0.0)), patch(
        "app.services.eval_service.eval_experiment_dao.insert_one",
        AsyncMock(),
    ) as mock_insert:
        experiment = await eval_service.run_evaluation("agent-1", "tenant-1")

    inserted = mock_insert.await_args.args[0]
    assert inserted.agent_id == "agent-1"
    assert inserted.tenant_id == "tenant-1"
    assert inserted.triggered_alert is False
    assert inserted.regression_reason is None
    assert inserted.config_snapshot["agent_id"] == "agent-1"
    assert experiment.run_id


@pytest.mark.asyncio
async def test_run_evaluation_baseline_delta_first_run() -> None:
    with patch("app.services.eval_service.eval_experiment_dao.find", AsyncMock(return_value=[])):
        delta = await eval_service._get_baseline_delta("agent-1", 0.9)
    assert delta == 0.0


@pytest.mark.asyncio
async def test_run_evaluation_baseline_delta_regression() -> None:
    prior = MagicMock()
    prior.ragas_scores.faithfulness = 0.8
    with patch("app.services.eval_service.eval_experiment_dao.find", AsyncMock(return_value=[prior])):
        delta = await eval_service._get_baseline_delta("agent-1", 0.6)
    assert delta == pytest.approx(-0.2)


@pytest.mark.asyncio
async def test_run_evaluation_no_dataset_raises() -> None:
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())), patch(
        "app.services.eval_service.eval_dataset_dao.find_one",
        AsyncMock(return_value=None),
    ), pytest.raises(EvalNoDatasetError):
        await eval_service.run_evaluation("agent-1", "tenant-1")


@pytest.mark.asyncio
async def test_regression_writes_cloudwatch_metric() -> None:
    agent = _make_agent()
    dataset = _make_dataset(1)
    fake_scores = RAGASScores(
        faithfulness=0.4,
        answer_relevancy=0.7,
        context_recall=0.6,
        context_precision=0.5,
    )
    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(return_value=fake_scores)
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=agent)), patch(
        "app.services.eval_service.eval_dataset_dao.find_one", AsyncMock(return_value=dataset)
    ), patch("app.services.eval_service._collect_eval_data", AsyncMock(return_value=[{"question": "q"}])), patch(
        "app.services.eval_service.asyncio.get_event_loop", return_value=mock_loop
    ), patch("app.services.eval_service._get_baseline_delta", AsyncMock(return_value=0.0)), patch(
        "app.services.eval_service._write_regression_metric", AsyncMock()
    ) as write_metric, patch("app.services.eval_service.eval_experiment_dao.insert_one", AsyncMock()):
        await eval_service.run_evaluation("agent-1", "tenant-1")

    write_metric.assert_awaited_once_with("tenant-1", "agent-1", 0.4)


@pytest.mark.asyncio
async def test_no_regression_no_cloudwatch_write() -> None:
    agent = _make_agent()
    dataset = _make_dataset(1)
    fake_scores = RAGASScores(
        faithfulness=0.8,
        answer_relevancy=0.7,
        context_recall=0.6,
        context_precision=0.5,
    )
    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(return_value=fake_scores)
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=agent)), patch(
        "app.services.eval_service.eval_dataset_dao.find_one", AsyncMock(return_value=dataset)
    ), patch("app.services.eval_service._collect_eval_data", AsyncMock(return_value=[{"question": "q"}])), patch(
        "app.services.eval_service.asyncio.get_event_loop", return_value=mock_loop
    ), patch("app.services.eval_service._get_baseline_delta", AsyncMock(return_value=0.0)), patch(
        "app.services.eval_service._write_regression_metric", AsyncMock()
    ) as write_metric, patch("app.services.eval_service.eval_experiment_dao.insert_one", AsyncMock()):
        await eval_service.run_evaluation("agent-1", "tenant-1")

    write_metric.assert_not_awaited()


@pytest.mark.asyncio
async def test_regression_metric_failure_does_not_raise() -> None:
    agent = _make_agent()
    dataset = _make_dataset(1)
    fake_scores = RAGASScores(
        faithfulness=0.4,
        answer_relevancy=0.7,
        context_recall=0.6,
        context_precision=0.5,
    )
    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(return_value=fake_scores)
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=agent)), patch(
        "app.services.eval_service.eval_dataset_dao.find_one", AsyncMock(return_value=dataset)
    ), patch("app.services.eval_service._collect_eval_data", AsyncMock(return_value=[{"question": "q"}])), patch(
        "app.services.eval_service.asyncio.get_event_loop", return_value=mock_loop
    ), patch("app.services.eval_service._get_baseline_delta", AsyncMock(return_value=0.0)), patch(
        "app.services.eval_service._write_regression_metric", AsyncMock(side_effect=RuntimeError("boom"))
    ), patch("app.services.eval_service.eval_experiment_dao.insert_one", AsyncMock()):
        experiment = await eval_service.run_evaluation("agent-1", "tenant-1")
    assert experiment.triggered_alert is True


@pytest.mark.asyncio
async def test_experiment_triggered_alert_true_on_regression() -> None:
    agent = _make_agent()
    dataset = _make_dataset(1)
    fake_scores = RAGASScores(
        faithfulness=0.4,
        answer_relevancy=0.7,
        context_recall=0.6,
        context_precision=0.5,
    )
    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(return_value=fake_scores)
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=agent)), patch(
        "app.services.eval_service.eval_dataset_dao.find_one", AsyncMock(return_value=dataset)
    ), patch("app.services.eval_service._collect_eval_data", AsyncMock(return_value=[{"question": "q"}])), patch(
        "app.services.eval_service.asyncio.get_event_loop", return_value=mock_loop
    ), patch("app.services.eval_service._get_baseline_delta", AsyncMock(return_value=0.0)), patch(
        "app.services.eval_service._write_regression_metric", AsyncMock()
    ), patch("app.services.eval_service.eval_experiment_dao.insert_one", AsyncMock()) as mock_insert:
        await eval_service.run_evaluation("agent-1", "tenant-1")
    assert mock_insert.await_args.args[0].triggered_alert is True


@pytest.mark.asyncio
async def test_experiment_triggered_alert_false_on_pass() -> None:
    agent = _make_agent()
    dataset = _make_dataset(1)
    fake_scores = RAGASScores(
        faithfulness=0.8,
        answer_relevancy=0.7,
        context_recall=0.6,
        context_precision=0.5,
    )
    mock_loop = MagicMock()
    mock_loop.run_in_executor = AsyncMock(return_value=fake_scores)
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=agent)), patch(
        "app.services.eval_service.eval_dataset_dao.find_one", AsyncMock(return_value=dataset)
    ), patch("app.services.eval_service._collect_eval_data", AsyncMock(return_value=[{"question": "q"}])), patch(
        "app.services.eval_service.asyncio.get_event_loop", return_value=mock_loop
    ), patch("app.services.eval_service._get_baseline_delta", AsyncMock(return_value=0.0)), patch(
        "app.services.eval_service._write_regression_metric", AsyncMock()
    ), patch("app.services.eval_service.eval_experiment_dao.insert_one", AsyncMock()) as mock_insert:
        await eval_service.run_evaluation("agent-1", "tenant-1")
    assert mock_insert.await_args.args[0].triggered_alert is False


@pytest.mark.asyncio
async def test_list_experiments_descending_order() -> None:
    doc = EvalExperiment(
        agent_id="agent-1",
        tenant_id="tenant-1",
        run_id="run-1",
        config_snapshot={"a": 1},
        ragas_scores=RAGASScores(
            faithfulness=0.9, answer_relevancy=0.8, context_recall=0.7, context_precision=0.6
        ),
        baseline_delta=0.0,
        triggered_alert=False,
        created_at=datetime.now(UTC),
    )
    doc.id = ObjectId()
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())), patch(
        "app.services.eval_service.eval_experiment_dao.find", AsyncMock(return_value=[doc])
    ) as find_mock:
        await eval_service.list_experiments("agent-1", "tenant-1")
    assert find_mock.await_args.kwargs["sort"] == [("_id", -1)]


@pytest.mark.asyncio
async def test_list_experiments_with_cursor() -> None:
    oid = ObjectId("507f1f77bcf86cd799439011")
    cursor = eval_service.encode_cursor(oid)
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())), patch(
        "app.services.eval_service.eval_experiment_dao.find", AsyncMock(return_value=[])
    ) as find_mock:
        await eval_service.list_experiments("agent-1", "tenant-1", cursor=cursor, limit=20)
    query = find_mock.await_args.args[0]
    assert query["_id"] == {"$lt": oid}


@pytest.mark.asyncio
async def test_list_experiments_has_next_cursor() -> None:
    docs: list[EvalExperiment] = []
    for i in range(21):
        doc = EvalExperiment(
            agent_id="agent-1",
            tenant_id="tenant-1",
            run_id=f"run-{i}",
            config_snapshot={"a": 1},
            ragas_scores=RAGASScores(
                faithfulness=0.9, answer_relevancy=0.8, context_recall=0.7, context_precision=0.6
            ),
            baseline_delta=0.0,
            triggered_alert=False,
            created_at=datetime.now(UTC),
        )
        doc.id = ObjectId(f"507f1f77bcf86cd7994390{10 + i:02d}")
        docs.append(doc)
    with patch("app.services.eval_service.agent_service.get_agent", AsyncMock(return_value=_make_agent())), patch(
        "app.services.eval_service.eval_experiment_dao.find", AsyncMock(return_value=docs)
    ):
        items, next_cursor = await eval_service.list_experiments("agent-1", "tenant-1", limit=20)
    assert len(items) == 20
    assert next_cursor is not None


@pytest.mark.asyncio
async def test_list_experiments_forbidden() -> None:
    with patch(
        "app.services.eval_service.agent_service.get_agent",
        AsyncMock(side_effect=ForbiddenError("forbidden")),
    ), pytest.raises(ForbiddenError):
        await eval_service.list_experiments("agent-1", "tenant-1")
