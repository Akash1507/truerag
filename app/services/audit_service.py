import aioboto3
from datetime import UTC, datetime
from decimal import Decimal

from app.core.config import get_settings
from app.utils.observability import LatencyTracker, _request_id_var, get_logger, log_stage_latency

logger = get_logger(__name__)

_default_session: aioboto3.Session = aioboto3.Session()


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
    settings = get_settings()
    _session = session or _default_session
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
