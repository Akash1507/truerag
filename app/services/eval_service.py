import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import aioboto3  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.errors import EvalNoDatasetError
from app.db.dao.eval_dataset_dao import eval_dataset_dao
from app.db.dao.eval_experiment_dao import eval_experiment_dao
from app.models.agent import AgentDocument
from app.models.eval import EvalDataset, EvalExperiment, EvalQuestion, RAGASScores
from app.pipelines.query.pipeline import run_query_pipeline
from app.services import agent_service
from app.utils import semantic_cache
from app.utils.observability import get_logger
from app.utils.pagination import decode_cursor, encode_cursor

logger = get_logger(__name__)
_default_session: aioboto3.Session = aioboto3.Session()


def _run_ragas_sync(eval_data: list[dict[str, Any]]) -> RAGASScores:
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

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


async def create_or_replace_dataset(
    agent_id: str,
    tenant_id: str,
    questions: list[EvalQuestion],
) -> EvalDataset:
    await agent_service.get_agent(agent_id, tenant_id)

    existing = await eval_dataset_dao.find_one({"agent_id": agent_id})
    if existing is not None:
        await existing.delete()

    dataset = EvalDataset(
        agent_id=agent_id,
        tenant_id=tenant_id,
        questions=questions,
        created_at=datetime.now(UTC),
    )
    await eval_dataset_dao.insert_one(dataset)

    await semantic_cache.invalidate(agent_id)

    logger.info(
        "eval_dataset_replaced",
        extra={
            "operation": "eval_dataset_replace",
            "extra_data": {
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "question_count": len(questions),
            },
        },
    )
    return dataset


async def get_dataset(agent_id: str, tenant_id: str) -> EvalDataset:
    await agent_service.get_agent(agent_id, tenant_id)
    dataset = await eval_dataset_dao.find_one({"agent_id": agent_id})
    if dataset is None:
        raise EvalNoDatasetError(f"No eval dataset found for agent '{agent_id}'")
    return dataset


async def _collect_eval_data(agent: AgentDocument, dataset: EvalDataset) -> list[dict[str, Any]]:
    eval_rows: list[dict[str, Any]] = []
    for item in dataset.questions:
        response = await run_query_pipeline(query=item.question, top_k=agent.top_k, agent=agent)
        eval_rows.append(
            {
                "question": item.question,
                "answer": response.answer,
                "contexts": [citation.chunk_text for citation in response.citations],
                "ground_truths": [item.expected_answer],
            }
        )
    return eval_rows


async def _get_baseline_delta(agent_id: str, current_faithfulness: float) -> float:
    prior = await eval_experiment_dao.find(
        {"agent_id": agent_id},
        sort=[("created_at", -1)],
        limit=1,
    )
    if not prior:
        return 0.0
    return current_faithfulness - prior[0].ragas_scores.faithfulness


async def _write_regression_metric(
    tenant_id: str,
    agent_id: str,
    faithfulness: float,
    session: aioboto3.Session | None = None,
) -> None:
    settings = get_settings()
    aws_session = session or _default_session
    try:
        async with aws_session.client(
            "cloudwatch",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as cw:
            await cw.put_metric_data(
                Namespace="TrueRAG/Eval",
                MetricData=[
                    {
                        "MetricName": "RAGASFaithfulness",
                        "Dimensions": [
                            {"Name": "TenantId", "Value": tenant_id},
                            {"Name": "AgentId", "Value": agent_id},
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


async def run_evaluation(agent_id: str, tenant_id: str) -> EvalExperiment:
    agent = await agent_service.get_agent(agent_id, tenant_id)

    dataset = await eval_dataset_dao.find_one({"agent_id": agent_id})
    if dataset is None:
        raise EvalNoDatasetError(f"No eval dataset found for agent '{agent_id}'")

    eval_data = await _collect_eval_data(agent, dataset)

    loop = asyncio.get_event_loop()
    ragas_scores = await loop.run_in_executor(None, _run_ragas_sync, eval_data)

    baseline_delta = await _get_baseline_delta(agent_id, ragas_scores.faithfulness)
    triggered_alert = ragas_scores.faithfulness < agent.faithfulness_threshold
    regression_reason: str | None = None
    if triggered_alert:
        regression_reason = (
            f"faithfulness {ragas_scores.faithfulness:.4f} below threshold "
            f"{agent.faithfulness_threshold:.4f}"
        )
        logger.warning(
            "faithfulness_regression_detected",
            extra={
                "operation": "regression_alert",
                "extra_data": {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "faithfulness": ragas_scores.faithfulness,
                    "threshold": agent.faithfulness_threshold,
                },
            },
        )
        try:
            await _write_regression_metric(tenant_id, agent_id, ragas_scores.faithfulness)
        except Exception as exc:
            logger.warning(
                "regression_metric_write_failed",
                extra={
                    "operation": "regression_alert",
                    "extra_data": {
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "error": str(exc),
                    },
                },
            )

    run_id = str(uuid.uuid4())
    config_snapshot = json.loads(agent.model_dump_json())

    experiment = EvalExperiment(
        agent_id=agent_id,
        tenant_id=tenant_id,
        run_id=run_id,
        config_snapshot=config_snapshot,
        ragas_scores=ragas_scores,
        baseline_delta=baseline_delta,
        triggered_alert=triggered_alert,
        regression_reason=regression_reason,
        created_at=datetime.now(UTC),
    )
    await eval_experiment_dao.insert_one(experiment)

    logger.info(
        "eval_run_complete",
        extra={
            "operation": "eval_run",
            "extra_data": {
                "agent_id": agent_id,
                "run_id": run_id,
                "faithfulness": ragas_scores.faithfulness,
            },
        },
    )

    return experiment


async def list_experiments(
    agent_id: str,
    tenant_id: str,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[EvalExperiment], str | None]:
    await agent_service.get_agent(agent_id, tenant_id)
    query: dict[str, object] = {"agent_id": agent_id}
    if cursor:
        oid = decode_cursor(cursor)
        query["_id"] = {"$lt": oid}
    docs = await eval_experiment_dao.find(query, sort=[("_id", -1)], limit=limit + 1)
    has_more = len(docs) > limit
    if has_more:
        docs = docs[:limit]
    next_cursor = encode_cursor(docs[-1].id) if has_more and docs and docs[-1].id else None
    return docs, next_cursor
