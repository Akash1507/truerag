import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import create_app


def _fake_metrics_module() -> types.ModuleType:
    module = types.ModuleType("app.services.metrics_service")
    module.METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
    module.generate_metrics_text = lambda: (
        b"# HELP truerag_queries_total Total queries\n"
        b"# TYPE truerag_queries_total counter\n"
        b"truerag_queries_total{tenant_id=\"t1\",agent_id=\"a1\"} 1.0\n"
        b"# HELP truerag_query_latency_seconds Query latency\n"
        b"# TYPE truerag_query_latency_seconds histogram\n"
        b"# HELP truerag_query_cost_tokens_total Query tokens\n"
        b"# TYPE truerag_query_cost_tokens_total counter\n"
        b"# HELP truerag_ingestion_jobs_total Ingestion jobs\n"
        b"# TYPE truerag_ingestion_jobs_total counter\n"
    )
    return module


def test_metrics_endpoint_is_unauthenticated_and_prometheus_text() -> None:
    mock_collection = MagicMock()
    mock_collection.create_index = AsyncMock(return_value="ok")
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.admin.command = AsyncMock(return_value={"ok": 1})
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    mock_motor.close = MagicMock()

    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=1)
    mock_pool.close = AsyncMock()

    fake_metrics = _fake_metrics_module()

    with (
        patch.dict(sys.modules, {"app.services.metrics_service": fake_metrics}),
        patch("app.main.AsyncIOMotorClient", return_value=mock_motor),
        patch("app.main.init_beanie", AsyncMock(return_value=None)),
        patch("app.main.asyncpg.create_pool", AsyncMock(return_value=mock_pool)),
        TestClient(create_app()) as client,
    ):
        response = client.get("/v1/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "truerag_queries_total" in response.text
    assert "truerag_query_latency_seconds" in response.text
    assert "truerag_query_cost_tokens_total" in response.text
    assert "truerag_ingestion_jobs_total" in response.text
