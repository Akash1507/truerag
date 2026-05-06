import logging
from typing import Any

from loguru import logger as loguru_logger

from app.utils.observability import (
    SENSITIVE_FIELDS,
    LatencyTracker,
    configure_logging,
    get_logger,
    log_stage_latency,
    mask_sensitive,
    reset_request_context,
    set_request_context,
)


def _capture_records() -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []

    def sink(message: Any) -> None:
        records.append(message.record)

    sink_id = loguru_logger.add(sink, level="DEBUG")
    return records, sink_id


def test_mask_sensitive_masks_all_sensitive_fields() -> None:
    payload = {field: "value" for field in SENSITIVE_FIELDS}
    payload["non_sensitive"] = "ok"

    masked = mask_sensitive(payload)

    for field in SENSITIVE_FIELDS:
        assert masked[field] == "***"
    assert masked["non_sensitive"] == "ok"


def test_mask_sensitive_masks_nested_structures() -> None:
    masked = mask_sensitive(
        {
            "nested": {
                "authorization": "Bearer token",
                "safe": "value",
            },
            "items": [
                {"token": "secret-token"},
                {"safe": "value"},
            ],
        }
    )
    nested = masked["nested"]
    items = masked["items"]

    assert isinstance(nested, dict)
    assert nested["authorization"] == "***"
    assert nested["safe"] == "value"
    assert isinstance(items, list)
    assert items[0]["token"] == "***"
    assert items[1]["safe"] == "value"


def test_configure_logging_intercepts_stdlib_messages() -> None:
    configure_logging("INFO")
    assert len(logging.getLogger().handlers) == 1

    records, sink_id = _capture_records()
    try:
        stdlib_logger = logging.getLogger("test.stdlib")
        stdlib_logger.info("intercepted_message")
    finally:
        loguru_logger.remove(sink_id)

    assert any(record["message"] == "intercepted_message" for record in records)


def test_get_logger_includes_module_and_request_context() -> None:
    configure_logging("INFO")
    records, sink_id = _capture_records()
    tokens = set_request_context(
        request_id="req-1234",
        tenant_id="tenant-abc",
        agent_id="agent-xyz",
    )
    try:
        logger = get_logger("test.observability")
        logger.bind(operation="test_operation").info("test_message")
    finally:
        reset_request_context(tokens)
        loguru_logger.remove(sink_id)

    record = next(r for r in records if r["message"] == "test_message")
    extra = record["extra"]
    assert extra["module"] == "test.observability"
    assert extra["request_id"] == "req-1234"
    assert extra["tenant_id"] == "tenant-abc"
    assert extra["agent_id"] == "agent-xyz"
    assert extra["operation"] == "test_operation"


def test_latency_tracker_returns_nonnegative() -> None:
    tracker = LatencyTracker()
    assert tracker.elapsed_ms() >= 0


def test_reset_request_context_restores_previous_values() -> None:
    configure_logging("INFO")
    records, sink_id = _capture_records()
    outer_tokens = set_request_context(
        request_id="outer-req",
        tenant_id="outer-tenant",
        agent_id="outer-agent",
    )
    inner_tokens = set_request_context(
        request_id="inner-req",
        tenant_id="inner-tenant",
        agent_id="inner-agent",
    )
    try:
        reset_request_context(inner_tokens)
        get_logger("test.reset").info("context_after_reset")
    finally:
        reset_request_context(outer_tokens)
        loguru_logger.remove(sink_id)

    record = next(r for r in records if r["message"] == "context_after_reset")
    extra = record["extra"]
    assert extra["request_id"] == "outer-req"
    assert extra["tenant_id"] == "outer-tenant"
    assert extra["agent_id"] == "outer-agent"


def test_log_stage_latency_emits_operation_and_latency() -> None:
    configure_logging("INFO")
    records, sink_id = _capture_records()
    tokens = set_request_context(
        request_id="req-9-1",
        tenant_id="tenant-9-1",
        agent_id="agent-9-1",
    )
    try:
        logger = get_logger("test.observability.stage_latency")
        log_stage_latency(logger, "retrieval", 23)
    finally:
        reset_request_context(tokens)
        loguru_logger.remove(sink_id)

    record = next(r for r in records if r["message"] == "retrieval")
    extra = record["extra"]
    assert extra["operation"] == "retrieval"
    assert extra["latency_ms"] == 23
    assert extra["request_id"] == "req-9-1"
    assert extra["tenant_id"] == "tenant-9-1"
    assert extra["agent_id"] == "agent-9-1"
