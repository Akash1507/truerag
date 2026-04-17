import json
import logging
import sys
import time
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_agent_id_var: ContextVar[str | None] = ContextVar("agent_id", default=None)
RequestContextTokens = tuple[Token[str], Token[str | None], Token[str | None]]


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


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "tenant_id": getattr(record, "tenant_id", None) or _tenant_id_var.get(),
            "agent_id": getattr(record, "agent_id", None) or _agent_id_var.get(),
            "request_id": getattr(record, "request_id", None) or _request_id_var.get(),
            "operation": str(getattr(record, "operation", "")),
            "latency_ms": getattr(record, "latency_ms", None),
            "extra": getattr(record, "extra_data", {}),
        }
        return json.dumps(entry)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(getattr(logging, get_settings().log_level, logging.INFO))
    return logger


class LatencyTracker:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)
