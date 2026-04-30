from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.observability import router
from app.main import create_app


def make_healthy_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.state.motor_client = MagicMock()
    app.state.motor_client.admin.command = AsyncMock(return_value={"ok": 1})
    app.state.pg_pool = MagicMock()
    app.state.pg_pool.fetchval = AsyncMock(return_value=1)

    s3 = AsyncMock()
    s3.head_bucket = AsyncMock(return_value={})
    sqs = AsyncMock()
    sqs.get_queue_attributes = AsyncMock(return_value={})

    def make_cm(client: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    app.state.aws_session = MagicMock()
    app.state.aws_session.client = MagicMock(
        side_effect=lambda service, **kwargs: make_cm(s3 if service == "s3" else sqs)
    )
    return app


def test_ready_all_healthy_returns_200() -> None:
    client = TestClient(make_healthy_app())
    resp = client.get("/v1/ready")
    assert resp.status_code == 200
    assert resp.json() == {"mongodb": "ok", "pgvector": "ok", "sqs": "ok", "s3": "ok"}


def test_lifespan_startup_populates_app_state() -> None:
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

    with patch("app.main.AsyncIOMotorClient", return_value=mock_motor), patch(
        "app.main.init_beanie", AsyncMock(return_value=None)
    ), patch("app.main.asyncpg.create_pool", AsyncMock(return_value=mock_pool)), TestClient(
        create_app()
    ) as client:
        assert client.app.state.motor_client is mock_motor
        assert client.app.state.pg_pool is mock_pool
