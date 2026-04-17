from httpx import AsyncClient


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
