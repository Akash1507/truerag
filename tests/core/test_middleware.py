import uuid

from httpx import AsyncClient


async def test_request_includes_x_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/v1/health")
    assert "X-Request-ID" in response.headers


async def test_request_id_is_valid_uuid_v4(client: AsyncClient) -> None:
    response = await client.get("/v1/health")
    request_id = response.headers["X-Request-ID"]
    parsed = uuid.UUID(request_id, version=4)
    assert str(parsed) == request_id
