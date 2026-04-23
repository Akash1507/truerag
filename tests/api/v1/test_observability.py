from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app


def make_healthy_app() -> FastAPI:
    application = create_app()

    mock_motor = MagicMock()
    mock_motor.admin.command = AsyncMock(return_value={"ok": 1})

    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=1)

    mock_sqs = AsyncMock()
    mock_sqs.get_queue_attributes = AsyncMock(return_value={})
    mock_dynamodb = AsyncMock()
    mock_dynamodb.describe_table = AsyncMock(return_value={})
    mock_s3 = AsyncMock()
    mock_s3.head_bucket = AsyncMock(return_value={})

    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(
        side_effect=[mock_sqs, mock_dynamodb, mock_s3]
    )
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    application.state.motor_client = mock_motor
    application.state.pg_pool = mock_pool
    application.state.aws_session = mock_session
    return application


def test_health_returns_200_ok() -> None:
    client = TestClient(make_healthy_app(), raise_server_exceptions=True)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_is_at_v1_health_not_observability() -> None:
    client = TestClient(make_healthy_app())
    assert client.get("/v1/health").status_code == 200
    # Auth middleware intercepts before routing, so old path returns 401.
    assert client.get("/v1/observability/health").status_code == 401


def test_ready_all_healthy_returns_200() -> None:
    client = TestClient(make_healthy_app())
    resp = client.get("/v1/ready")
    assert resp.status_code == 200
    assert resp.json() == {
        "mongodb": "ok",
        "pgvector": "ok",
        "sqs": "ok",
        "dynamodb": "ok",
        "s3": "ok",
    }


def test_ready_mongodb_down_returns_503() -> None:
    app = create_app()

    mock_motor = MagicMock()
    mock_motor.admin.command = AsyncMock(side_effect=Exception("connection refused"))
    app.state.motor_client = mock_motor
    app.state.pg_pool = MagicMock()
    app.state.aws_session = MagicMock()

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/v1/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert "mongodb" in body["error"]["message"]
    assert "request_id" in body["error"]


def test_ready_pgvector_down_returns_503() -> None:
    app = create_app()

    mock_motor = MagicMock()
    mock_motor.admin.command = AsyncMock(return_value={"ok": 1})
    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(side_effect=Exception("pgvector down"))
    app.state.motor_client = mock_motor
    app.state.pg_pool = mock_pool
    app.state.aws_session = MagicMock()

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/v1/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert "pgvector" in body["error"]["message"]


def test_ready_sqs_down_returns_503() -> None:
    app = create_app()

    mock_motor = MagicMock()
    mock_motor.admin.command = AsyncMock(return_value={"ok": 1})
    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=1)

    mock_sqs = AsyncMock()
    mock_sqs.get_queue_attributes = AsyncMock(side_effect=Exception("sqs down"))
    mock_session = MagicMock()
    mock_session.client.return_value.__aenter__ = AsyncMock(return_value=mock_sqs)
    mock_session.client.return_value.__aexit__ = AsyncMock(return_value=False)

    app.state.motor_client = mock_motor
    app.state.pg_pool = mock_pool
    app.state.aws_session = mock_session

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/v1/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert "sqs" in body["error"]["message"]


def test_lifespan_startup_populates_app_state() -> None:
    mock_collection = MagicMock()
    mock_collection.create_index = AsyncMock(return_value="name_1")
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_motor = MagicMock()
    mock_motor.admin.command = AsyncMock(return_value={"ok": 1})
    mock_motor.__getitem__ = MagicMock(return_value=mock_db)
    mock_motor.close = MagicMock()

    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=1)
    mock_pool.close = AsyncMock()

    with (
        patch("app.main.AsyncIOMotorClient", return_value=mock_motor),
        patch("app.main.asyncpg.create_pool", AsyncMock(return_value=mock_pool)),
        TestClient(create_app()) as client,
    ):
        assert client.app.state.motor_client is mock_motor
        assert client.app.state.pg_pool is mock_pool
        assert hasattr(client.app.state, "aws_session")


def test_lifespan_mongodb_failure_raises_runtime_error() -> None:
    mock_motor = MagicMock()
    mock_motor.admin.command = AsyncMock(side_effect=Exception("conn refused"))
    mock_motor.close = MagicMock()

    with (
        patch("app.main.AsyncIOMotorClient", return_value=mock_motor),
        pytest.raises(RuntimeError, match="MongoDB connection failed"),
        TestClient(create_app()),
    ):
        pass
