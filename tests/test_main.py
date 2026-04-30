from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.main import create_app


async def test_app_starts(client: AsyncClient) -> None:
    resp = await client.get("/docs")
    assert resp.status_code == 200


async def test_redoc_available(client: AsyncClient) -> None:
    resp = await client.get("/redoc")
    assert resp.status_code == 200


async def test_all_routes_prefixed_v1(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    schema = resp.json()
    paths = list(schema.get("paths", {}).keys())
    for path in paths:
        assert path.startswith("/v1/"), f"Route {path!r} not prefixed /v1/"


def test_create_app_available_with_mocked_init_beanie() -> None:
    with patch("app.main.init_beanie", AsyncMock(return_value=None)):
        app = create_app()
    assert app is not None
