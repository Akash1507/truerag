import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import aioboto3  # type: ignore[import-untyped]
from fastapi import BackgroundTasks

from app.core.config import Settings, get_settings
from app.core.errors import EvalNoDatasetError, InvalidCursorError, TrueRAGError
from app.db.dao.eval_dataset_dao import EvalDatasetDAO, eval_dataset_dao
from app.db.dao.eval_experiment_dao import EvalExperimentDAO, eval_experiment_dao
from app.models.agent import AgentDocument
from app.models.eval import (
    EvalDataset,
    EvalDatasetCreateResponse,
    EvalDatasetGetResponse,
    EvalExperiment,
    EvalExperimentSummary,
    EvalHistoryResponse,
    EvalQuestion,
    EvalRunAcceptedResponse,
    EvalRunResponse,
    RAGASScores,
)
from app.pipelines.query.pipeline import run_query_pipeline
from app.services.agent_service import AgentService, agent_service
from app.utils import semantic_cache
from app.utils.observability import get_logger
from app.utils.pagination import decode_cursor, encode_cursor

logger = get_logger(__name__)
_default_session: aioboto3.Session = aioboto3.Session()

P = ParamSpec("P")
R = TypeVar("R")

try:
    from app.core.decorators import service_method  # type: ignore[import-not-found]
except Exception:
    def service_method(
        operation: str,
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                try:
                    return await func(*args, **kwargs)
                except TrueRAGError:
                    raise
                except ValueError as exc:
                    raise InvalidCursorError(str(exc)) from exc
                except Exception:
                    logger.exception(
                        "service_method_error",
                        extra={"operation": operation, "extra_data": {"service": "eval_service"}},
                    )
                    raise

            return wrapper

        return decorator


def _run_ragas_sync(eval_data: list[dict[str, Any]], openai_api_key: str, llm_model: str) -> RAGASScores:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import evaluate
    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

    llm = LangchainLLMWrapper(ChatOpenAI(model=llm_model, api_key=openai_api_key))  # type: ignore[arg-type]
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(api_key=openai_api_key))  # type: ignore[arg-type]

    samples = [
        SingleTurnSample(
            user_input=row["question"],
            response=row["answer"],
            retrieved_contexts=row["contexts"],
            reference=row["ground_truths"][0] if row["ground_truths"] else "",
        )
        for row in eval_data
    ]
    dataset = EvaluationDataset(samples=samples)
    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_recall, context_precision],
        llm=llm,
        embeddings=embeddings,
    )
    import statistics

    def _mean(vals: Any) -> float:
        if isinstance(vals, list):
            clean = [v for v in vals if v is not None]
            return statistics.mean(clean) if clean else 0.0
        return float(vals)

    return RAGASScores(
        faithfulness=_mean(result["faithfulness"]),
        answer_relevancy=_mean(result["answer_relevancy"]),
        context_recall=_mean(result["context_recall"]),
        context_precision=_mean(result["context_precision"]),
    )


class EvalService:
    def __init__(
        self,
        eval_dataset_dao_dep: EvalDatasetDAO,
        eval_experiment_dao_dep: EvalExperimentDAO,
        agent_service_dep: AgentService,
        settings_getter: Callable[[], Settings] = get_settings,
        default_session: aioboto3.Session = _default_session,
    ) -> None:
        self._eval_dataset_dao = eval_dataset_dao_dep
        self._eval_experiment_dao = eval_experiment_dao_dep
        self._agent_service = agent_service_dep
        self._settings_getter = settings_getter
        self._default_session = default_session

    async def _collect_eval_data(
        self,
        agent: AgentDocument,
        dataset: EvalDataset,
    ) -> list[dict[str, Any]]:
        eval_rows: list[dict[str, Any]] = []
        for idx, item in enumerate(dataset.questions):
            logger.info(
                "eval_query_start",
                extra={
                    "operation": "collect_eval_data",
                    "extra_data": {
                        "question_index": idx,
                        "question": item.question[:80],
                        "agent_id": agent.agent_id,
                    },
                },
            )
            try:
                response = await run_query_pipeline(query=item.question, top_k=agent.top_k, agent=agent)
            except Exception as exc:
                logger.error(
                    "eval_query_failed",
                    extra={
                        "operation": "collect_eval_data",
                        "extra_data": {
                            "question_index": idx,
                            "question": item.question[:80],
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                    },
                )
                raise
            eval_rows.append(
                {
                    "question": item.question,
                    "answer": response.answer,
                    "contexts": [citation.chunk_text for citation in response.citations],
                    "ground_truths": [item.expected_answer],
                }
            )
            logger.info(
                "eval_query_done",
                extra={
                    "operation": "collect_eval_data",
                    "extra_data": {
                        "question_index": idx,
                        "route": "direct" if not response.citations else "retrieval",
                        "citation_count": len(response.citations),
                    },
                },
            )
        return eval_rows

    async def _get_baseline_delta(self, agent_id: str, current_faithfulness: float) -> float:
        prior = await self._eval_experiment_dao.find(
            {"agent_id": agent_id},
            sort=[("created_at", -1)],
            limit=1,
        )
        if not prior:
            return 0.0
        return current_faithfulness - prior[0].ragas_scores.faithfulness

    async def _write_regression_metric(
        self,
        tenant_id: str,
        agent_id: str,
        faithfulness: float,
        session: aioboto3.Session | None = None,
    ) -> None:
        settings = self._settings_getter()
        aws_session = session or self._default_session
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
                    "extra_data": {
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "error": str(exc),
                    },
                },
            )

    @service_method("create_or_replace_eval_dataset")
    async def create_eval_dataset(
        self,
        agent_id: str,
        tenant_id: str,
        questions: list[EvalQuestion],
    ) -> EvalDatasetCreateResponse:
        await self._agent_service.get_agent(agent_id, tenant_id)

        await self._eval_dataset_dao.delete_many({"agent_id": agent_id, "tenant_id": tenant_id})

        dataset = EvalDataset(
            agent_id=agent_id,
            tenant_id=tenant_id,
            questions=questions,
            created_at=datetime.now(UTC),
        )
        await self._eval_dataset_dao.insert_one(dataset)
        try:
            await semantic_cache.invalidate(agent_id)
        except Exception as exc:
            logger.warning(
                "semantic_cache_invalidate_failed",
                extra={
                    "operation": "eval_dataset_replace",
                    "extra_data": {"agent_id": agent_id, "error": str(exc)},
                },
            )

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
        return EvalDatasetCreateResponse(
            dataset_id=str(dataset.id),
            agent_id=dataset.agent_id,
            tenant_id=dataset.tenant_id,
            question_count=len(dataset.questions),
            created_at=dataset.created_at,
        )

    async def _get_dataset_doc(self, agent_id: str, tenant_id: str) -> EvalDataset:
        await self._agent_service.get_agent(agent_id, tenant_id)
        dataset = await self._eval_dataset_dao.find_one({"agent_id": agent_id, "tenant_id": tenant_id})
        if dataset is None:
            raise EvalNoDatasetError(f"No eval dataset found for agent '{agent_id}'")
        return dataset

    @service_method("get_eval_dataset")
    async def get_dataset(self, agent_id: str, tenant_id: str) -> EvalDatasetGetResponse:
        dataset = await self._get_dataset_doc(agent_id, tenant_id)
        return EvalDatasetGetResponse(
            dataset_id=str(dataset.id),
            agent_id=dataset.agent_id,
            questions=dataset.questions,
            created_at=dataset.created_at,
        )

    @service_method("run_evaluation")
    async def run_evaluation(self, agent_id: str, tenant_id: str) -> EvalExperiment:
        agent = await self._agent_service.get_agent(agent_id, tenant_id)

        dataset = await self._eval_dataset_dao.find_one({"agent_id": agent_id, "tenant_id": tenant_id})
        if dataset is None:
            raise EvalNoDatasetError(f"No eval dataset found for agent '{agent_id}'")

        eval_data = await _collect_eval_data(agent, dataset)

        settings = self._settings_getter()
        loop = asyncio.get_event_loop()
        ragas_scores = await loop.run_in_executor(
            None, _run_ragas_sync, eval_data, settings.openai_api_key, settings.openai_llm_model
        )

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
        await self._eval_experiment_dao.insert_one(experiment)

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

    @service_method("list_eval_experiments")
    async def list_experiments(
        self,
        agent_id: str,
        tenant_id: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> tuple[list[EvalExperiment], str | None]:
        await self._agent_service.get_agent(agent_id, tenant_id)
        query: dict[str, object] = {"agent_id": agent_id, "tenant_id": tenant_id}
        if cursor:
            oid = decode_cursor(cursor)
            query["_id"] = {"$lt": oid}
        docs = await self._eval_experiment_dao.find(query, sort=[("_id", -1)], limit=limit + 1)
        has_more = len(docs) > limit
        if has_more:
            docs = docs[:limit]
        next_cursor = encode_cursor(docs[-1].id) if has_more and docs and docs[-1].id else None
        return docs, next_cursor

    @service_method("run_eval")
    async def run_eval(
        self,
        agent_id: str,
        tenant_id: str,
        background_tasks: BackgroundTasks,
    ) -> EvalRunResponse | EvalRunAcceptedResponse:
        dataset = await self._get_dataset_doc(agent_id, tenant_id)
        if len(dataset.questions) > 20:
            run_id = str(uuid.uuid4())
            background_tasks.add_task(self.run_evaluation, agent_id, tenant_id)
            return EvalRunAcceptedResponse(run_id=run_id, agent_id=agent_id)

        experiment = await self.run_evaluation(agent_id, tenant_id)
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

    @service_method("get_eval_history")
    async def get_eval_history(
        self,
        agent_id: str,
        tenant_id: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> EvalHistoryResponse:
        experiments, next_cursor = await self.list_experiments(
            agent_id=agent_id,
            tenant_id=tenant_id,
            cursor=cursor,
            limit=limit,
        )
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

    # Legacy method names preserved for compatibility.
    async def create_or_replace_dataset(
        self,
        agent_id: str,
        tenant_id: str,
        questions: list[EvalQuestion],
    ) -> EvalDataset:
        await self._agent_service.get_agent(agent_id, tenant_id)
        await self._eval_dataset_dao.delete_many({"agent_id": agent_id, "tenant_id": tenant_id})
        dataset = EvalDataset(
            agent_id=agent_id,
            tenant_id=tenant_id,
            questions=questions,
            created_at=datetime.now(UTC),
        )
        await self._eval_dataset_dao.insert_one(dataset)
        try:
            await semantic_cache.invalidate(agent_id)
        except Exception as exc:
            logger.warning(
                "semantic_cache_invalidate_failed",
                extra={
                    "operation": "eval_dataset_replace",
                    "extra_data": {"agent_id": agent_id, "error": str(exc)},
                },
            )
        return dataset


eval_service = EvalService(
    eval_dataset_dao_dep=eval_dataset_dao,
    eval_experiment_dao_dep=eval_experiment_dao,
    agent_service_dep=agent_service,
)


# Legacy compatibility wrappers for non-story call sites.
async def create_or_replace_dataset(
    agent_id: str,
    tenant_id: str,
    questions: list[EvalQuestion],
) -> EvalDataset:
    return await eval_service.create_or_replace_dataset(agent_id, tenant_id, questions)


async def get_dataset(agent_id: str, tenant_id: str) -> EvalDatasetGetResponse:
    return await eval_service.get_dataset(agent_id, tenant_id)


async def run_evaluation(agent_id: str, tenant_id: str) -> EvalExperiment:
    return await eval_service.run_evaluation(agent_id, tenant_id)


async def list_experiments(
    agent_id: str,
    tenant_id: str,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[EvalExperiment], str | None]:
    return await eval_service.list_experiments(agent_id, tenant_id, cursor, limit)


async def _collect_eval_data(agent: AgentDocument, dataset: EvalDataset) -> list[dict[str, Any]]:
    return await eval_service._collect_eval_data(agent, dataset)


async def _get_baseline_delta(agent_id: str, current_faithfulness: float) -> float:
    return await eval_service._get_baseline_delta(agent_id, current_faithfulness)


async def _write_regression_metric(
    tenant_id: str,
    agent_id: str,
    faithfulness: float,
    session: aioboto3.Session | None = None,
) -> None:
    await eval_service._write_regression_metric(tenant_id, agent_id, faithfulness, session)
