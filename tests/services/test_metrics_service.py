import pytest

metrics_service = pytest.importorskip("app.services.metrics_service")


def test_generate_metrics_text_returns_prometheus_bytes() -> None:
    if hasattr(metrics_service, "record_query"):
        metrics_service.record_query("tenant-test", "agent-test", 125, 42)

    payload = metrics_service.generate_metrics_text()

    assert isinstance(payload, bytes)
    text = payload.decode("utf-8")
    assert "truerag_queries_total" in text
    assert "truerag_query_latency_seconds" in text
    assert "truerag_query_cost_tokens_total" in text
    assert "truerag_ingestion_jobs_total" in text
