import uuid
from typing import Any

from httpx import AsyncClient
from loguru import logger as loguru_logger

from app.utils.observability import configure_logging


async def test_request_includes_x_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/v1/health")
    assert "X-Request-ID" in response.headers


async def test_request_id_is_valid_uuid_v4(client: AsyncClient) -> None:
    response = await client.get("/v1/health")
    request_id = response.headers["X-Request-ID"]
    parsed = uuid.UUID(request_id, version=4)
    assert str(parsed) == request_id


async def test_request_response_middleware_logs_masked_headers(client: AsyncClient) -> None:
    configure_logging("INFO")
    records: list[dict[str, Any]] = []

    def sink(message: Any) -> None:
        records.append(message.record)

    sink_id = loguru_logger.add(sink, level="INFO")
    try:
        response = await client.get(
            "/v1/health",
            headers={
                "Authorization": "Bearer abc",
                "X-API-Key": "raw-api-key",
            },
        )
    finally:
        loguru_logger.remove(sink_id)

    assert response.status_code == 200

    request_record = next(record for record in records if record["message"] == "http_request")
    request_extra = request_record["extra"]
    assert request_extra["operation"] == "http_request"
    assert request_extra["method"] == "GET"
    assert request_extra["path"] == "/v1/health"
    assert request_extra["headers"]["authorization"] == "***"
    assert request_extra["headers"]["x-api-key"] == "***"

    response_record = next(record for record in records if record["message"] == "http_response")
    response_extra = response_record["extra"]
    assert response_extra["operation"] == "http_response"
    assert response_extra["method"] == "GET"
    assert response_extra["path"] == "/v1/health"
    assert response_extra["status_code"] == 200
    assert isinstance(response_extra["latency_ms"], int)
    assert response_extra["latency_ms"] >= 0
