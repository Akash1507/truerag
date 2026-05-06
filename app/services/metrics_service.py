from datetime import UTC, datetime, timedelta
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

from app.core.config import get_settings
from app.core.errors import InvalidCursorError, ProviderUnavailableError, TrueRAGError
from app.db.dao.query_cost_dao import QueryCostDAO, query_cost_dao

_REGISTRY = CollectorRegistry()
_QUERY_COUNTER = Counter(
    "truerag_queries_total",
    "Total number of queries processed",
    ["tenant_id", "agent_id"],
    registry=_REGISTRY,
)
_QUERY_LATENCY = Histogram(
    "truerag_query_latency_seconds",
    "Query end-to-end latency in seconds",
    ["tenant_id", "agent_id"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=_REGISTRY,
)
_QUERY_COST_TOKENS = Counter(
    "truerag_query_cost_tokens_total",
    "Total tokens (prompt + completion) consumed in queries",
    ["tenant_id", "agent_id"],
    registry=_REGISTRY,
)
_INGESTION_JOBS = Counter(
    "truerag_ingestion_jobs_total",
    "Ingestion job counts (worker-side, from CloudWatch log metric filters; API-process counter is always 0)",
    ["tenant_id", "agent_id", "status"],
    registry=_REGISTRY,
)
METRICS_CONTENT_TYPE: str = CONTENT_TYPE_LATEST

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
                    raise

            return wrapper

        return decorator


class MetricsService:
    def __init__(self, query_cost_dao_dep: QueryCostDAO) -> None:
        self._query_cost_dao = query_cost_dao_dep

    def record_query(self, tenant_id: str, agent_id: str, latency_ms: int, total_tokens: int) -> None:
        labels = {"tenant_id": tenant_id, "agent_id": agent_id}
        _QUERY_COUNTER.labels(**labels).inc()
        _QUERY_LATENCY.labels(**labels).observe(max(latency_ms, 0) / 1000.0)
        if total_tokens > 0:
            _QUERY_COST_TOKENS.labels(**labels).inc(total_tokens)

    def generate_metrics_text(self) -> bytes:
        return generate_latest(_REGISTRY)

    @service_method("get_cost_breakdown")
    async def get_cost_breakdown(self, time_window_hours: int = 24) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(hours=time_window_hours)
        pipeline: list[dict[str, Any]] = [
            {"$match": {"timestamp": {"$gte": cutoff}}},
            {
                "$group": {
                    "_id": {"tenant_id": "$tenant_id", "agent_id": "$agent_id"},
                    "total_prompt_tokens": {"$sum": "$prompt_tokens"},
                    "total_completion_tokens": {"$sum": "$completion_tokens"},
                    "total_embedding_calls": {"$sum": "$embedding_calls"},
                    "total_reranker_calls": {"$sum": "$reranker_calls"},
                }
            },
            {"$sort": {"_id.tenant_id": 1, "_id.agent_id": 1}},
        ]
        rows = await self._query_cost_dao.aggregate(pipeline)
        return [
            {
                "tenant_id": row["_id"]["tenant_id"],
                "agent_id": row["_id"]["agent_id"],
                "total_prompt_tokens": int(row.get("total_prompt_tokens", 0) or 0),
                "total_completion_tokens": int(row.get("total_completion_tokens", 0) or 0),
                "total_embedding_calls": int(row.get("total_embedding_calls", 0) or 0),
                "total_reranker_calls": int(row.get("total_reranker_calls", 0) or 0),
            }
            for row in rows
        ]

    @service_method("readiness_check")
    async def readiness_check(self, request: Request) -> dict[str, str]:
        settings = get_settings()

        try:
            await request.app.state.motor_client.admin.command("ping")
        except Exception as exc:
            raise ProviderUnavailableError(f"mongodb unavailable: {exc}") from exc

        try:
            await request.app.state.pg_pool.fetchval("SELECT 1")
        except Exception as exc:
            raise ProviderUnavailableError(f"pgvector unavailable: {exc}") from exc

        try:
            async with request.app.state.aws_session.client(
                "sqs",
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            ) as sqs:
                await sqs.get_queue_attributes(
                    QueueUrl=settings.sqs_ingestion_queue_url,
                    AttributeNames=["ApproximateNumberOfMessages"],
                )
        except Exception as exc:
            raise ProviderUnavailableError(f"sqs unavailable: {exc}") from exc

        try:
            async with request.app.state.aws_session.client(
                "s3",
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            ) as s3:
                await s3.head_bucket(Bucket=settings.s3_document_bucket)
        except Exception as exc:
            raise ProviderUnavailableError(f"s3 unavailable: {exc}") from exc

        return {"mongodb": "ok", "pgvector": "ok", "sqs": "ok", "s3": "ok"}


metrics_service = MetricsService(query_cost_dao_dep=query_cost_dao)


def record_query(tenant_id: str, agent_id: str, latency_ms: int, total_tokens: int) -> None:
    metrics_service.record_query(tenant_id, agent_id, latency_ms, total_tokens)


def generate_metrics_text() -> bytes:
    return metrics_service.generate_metrics_text()


async def get_cost_breakdown(time_window_hours: int = 24) -> list[dict[str, Any]]:
    return await metrics_service.get_cost_breakdown(time_window_hours)
