import json
import logging

from app.utils.observability import JSONFormatter, LatencyTracker, get_logger, set_request_context


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
    set_request_context(request_id="test-uuid-1234")
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


def test_latency_tracker_returns_nonnegative() -> None:
    tracker = LatencyTracker()
    assert tracker.elapsed_ms() >= 0


def test_set_request_context_sets_all_fields() -> None:
    set_request_context(request_id="req-123", tenant_id="tenant-abc", agent_id="agent-xyz")
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
