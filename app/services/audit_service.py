from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from typing import ParamSpec, TypeVar

import aioboto3

from app.core.config import Settings, get_settings
from app.core.errors import InvalidCursorError, TrueRAGError
from app.utils.observability import LatencyTracker, _request_id_var, get_logger, log_stage_latency

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
                    raise

            return wrapper

        return decorator


class AuditService:
    def __init__(
        self,
        settings_getter: Callable[[], Settings] = get_settings,
        default_session: aioboto3.Session = _default_session,
    ) -> None:
        self._settings_getter = settings_getter
        self._default_session = default_session

    @service_method("write_audit_log")
    async def write_audit_log(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        api_key_hash: str,
        query_hash: str,
        response_confidence: float,
        cache_hit: bool = False,
        session: aioboto3.Session | None = None,
    ) -> None:
        settings = self._settings_getter()
        _session = session or self._default_session
        timestamp = datetime.now(UTC).isoformat()
        tracker = LatencyTracker()
        try:
            async with _session.resource(
                "dynamodb",
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            ) as dynamodb:
                table = await dynamodb.Table(settings.dynamodb_audit_table)
                await table.put_item(
                    Item={
                        "tenant_id": tenant_id,
                        "sort_key": f"{timestamp}#{query_hash}",
                        "agent_id": agent_id,
                        "api_key_hash": api_key_hash,
                        "query_hash": query_hash,
                        "timestamp": timestamp,
                        "response_confidence": Decimal(str(response_confidence)),
                        "cache_hit": cache_hit,
                    }
                )
        except Exception as exc:
            log_stage_latency(logger, "audit_log_write", tracker.elapsed_ms())
            logger.error(
                "audit_log_write_failed",
                extra={
                    "operation": "audit_log_write",
                    "extra_data": {
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "error": str(exc),
                        "request_id": _request_id_var.get(),
                    },
                },
            )
        else:
            log_stage_latency(logger, "audit_log_write", tracker.elapsed_ms())


audit_service = AuditService()


async def write_audit_log(
    *,
    tenant_id: str,
    agent_id: str,
    api_key_hash: str,
    query_hash: str,
    response_confidence: float,
    cache_hit: bool = False,
    session: aioboto3.Session | None = None,
) -> None:
    await audit_service.write_audit_log(
        tenant_id=tenant_id,
        agent_id=agent_id,
        api_key_hash=api_key_hash,
        query_hash=query_hash,
        response_confidence=response_confidence,
        cache_hit=cache_hit,
        session=session,
    )
