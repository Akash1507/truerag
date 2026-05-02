import json
import logging

from app.utils.observability import (
    JSONFormatter,
    LatencyTracker,
    get_logger,
    log_stage_latency,
    reset_request_context,
    set_request_context,
)


def test_get_logger_returns_logger_with_stream_handler() -> None:
    logger = get_logger("test.observability")
    assert isinstance(logger, logging.Logger)
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


def test_json_formatter_produces_valid_json() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    required_fields = {
        "timestamp", "level", "tenant_id", "agent_id",
        "request_id", "operation", "latency_ms", "extra",
    }
    assert required_fields == set(parsed.keys())


def test_json_formatter_all_required_field_values() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=(),
        exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["level"] == "INFO"
    assert isinstance(parsed["timestamp"], str)


def test_request_id_propagates_to_log() -> None:
    tokens = set_request_context(request_id="test-uuid-1234")
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["request_id"] == "test-uuid-1234"
    reset_request_context(tokens)


def test_latency_tracker_returns_nonnegative() -> None:
    tracker = LatencyTracker()
    assert tracker.elapsed_ms() >= 0


def test_set_request_context_sets_all_fields() -> None:
    tokens = set_request_context(
        request_id="req-123",
        tenant_id="tenant-abc",
        agent_id="agent-xyz",
    )
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["request_id"] == "req-123"
    assert parsed["tenant_id"] == "tenant-abc"
    assert parsed["agent_id"] == "agent-xyz"
    reset_request_context(tokens)


def test_reset_request_context_restores_previous_values() -> None:
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

    reset_request_context(inner_tokens)

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["request_id"] == "outer-req"
    assert parsed["tenant_id"] == "outer-tenant"
    assert parsed["agent_id"] == "outer-agent"
    reset_request_context(outer_tokens)


def test_log_stage_latency_emits_operation_and_latency() -> None:
    logger = logging.getLogger("test.observability.stage_latency")
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = True

    tokens = set_request_context(
        request_id="req-9-1",
        tenant_id="tenant-9-1",
        agent_id="agent-9-1",
    )
    try:
        record: logging.LogRecord | None = None

        class _Capture(logging.Handler):
            def emit(self, rec: logging.LogRecord) -> None:
                nonlocal record
                record = rec

        handler = _Capture()
        logger.addHandler(handler)
        log_stage_latency(logger, "retrieval", 23)
    finally:
        reset_request_context(tokens)
        logger.handlers = []

    assert record is not None
    formatter = JSONFormatter()
    parsed = json.loads(formatter.format(record))
    assert parsed["operation"] == "retrieval"
    assert parsed["latency_ms"] == 23
    assert parsed["request_id"] == "req-9-1"
    assert parsed["tenant_id"] == "tenant-9-1"
    assert parsed["agent_id"] == "agent-9-1"
