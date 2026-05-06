import logging
import sys
import time
from contextvars import ContextVar, Token
from typing import Any, cast

from loguru import logger

SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "api_key",
        "password",
        "token",
        "secret",
        "authorization",
        "x-api-key",
    }
)

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_agent_id_var: ContextVar[str | None] = ContextVar("agent_id", default=None)
RequestContextTokens = tuple[Token[str], Token[str | None], Token[str | None]]


def _mask_nested(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, nested_value in value.items():
            if isinstance(key, str) and key.lower() in SENSITIVE_FIELDS:
                masked[key] = "***"
            elif isinstance(key, str):
                masked[key] = _mask_nested(nested_value)
            else:
                masked[key] = nested_value
        return masked
    if isinstance(value, list):
        return [_mask_nested(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_nested(item) for item in value)
    return value


def mask_sensitive(data: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_FIELDS:
            masked[key] = "***"
        else:
            masked[key] = _mask_nested(value)
    return masked


def _patch_record(record: dict[str, Any]) -> None:
    extra: dict[str, Any] = record["extra"]
    legacy_extra = extra.pop("extra", None)
    legacy_payload: dict[str, Any] = legacy_extra if isinstance(legacy_extra, dict) else {}
    legacy_data = legacy_payload.get("extra_data")

    if isinstance(legacy_data, dict):
        extra["extra_data"] = mask_sensitive(legacy_data)
        for context_key in ("tenant_id", "agent_id", "request_id"):
            if context_key not in extra and isinstance(legacy_data.get(context_key), str):
                extra[context_key] = legacy_data[context_key]

    if "operation" not in extra and isinstance(legacy_payload.get("operation"), str):
        extra["operation"] = legacy_payload["operation"]
    if "latency_ms" not in extra and isinstance(legacy_payload.get("latency_ms"), int):
        extra["latency_ms"] = legacy_payload["latency_ms"]

    if not isinstance(extra.get("request_id"), str) or not extra["request_id"]:
        extra["request_id"] = _request_id_var.get()
    if extra.get("tenant_id") is None:
        extra["tenant_id"] = _tenant_id_var.get()
    if extra.get("agent_id") is None:
        extra["agent_id"] = _agent_id_var.get()
    extra.setdefault("operation", "")

    for key, value in list(extra.items()):
        if isinstance(key, str) and key.lower() in SENSITIVE_FIELDS:
            extra[key] = "***"
        elif isinstance(value, (dict, list, tuple)):
            extra[key] = _mask_nested(value)


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def set_request_context(
    *,
    request_id: str,
    tenant_id: str | None = None,
    agent_id: str | None = None,
) -> RequestContextTokens:
    request_token = _request_id_var.set(request_id)
    tenant_token = _tenant_id_var.set(tenant_id)
    agent_token = _agent_id_var.set(agent_id)
    return request_token, tenant_token, agent_token


def reset_request_context(tokens: RequestContextTokens) -> None:
    request_token, tenant_token, agent_token = tokens
    _request_id_var.reset(request_token)
    _tenant_id_var.reset(tenant_token)
    _agent_id_var.reset(agent_token)


def configure_logging(level: str = "INFO") -> None:
    logger.configure(
        patcher=cast(Any, _patch_record),
        extra={
            "request_id": "",
            "tenant_id": None,
            "agent_id": None,
            "operation": "",
        },
    )
    logger.remove()
    logger.add(
        sys.stdout,
        level=level.upper(),
        serialize=True,
        format="{message}",
        backtrace=False,
        diagnose=False,
    )
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)


def get_logger(name: str) -> Any:
    return logger.bind(module=name)


class LatencyTracker:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)


def log_stage_latency(
    logger: Any,
    operation: str,
    latency_ms: int,
) -> None:
    logger.bind(operation=operation, latency_ms=latency_ms).info(operation)
