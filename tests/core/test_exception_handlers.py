import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import (
    NamespaceViolationError,
    ProviderUnavailableError,
    RateLimitError,
    TrueRAGError,
)
from app.core.exception_handlers import generic_exception_handler, truerag_exception_handler
from app.core.middleware import RequestIDMiddleware
from app.main import app as real_app

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def make_test_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(RequestIDMiddleware)
    test_app.add_exception_handler(TrueRAGError, truerag_exception_handler)  # type: ignore[arg-type]
    test_app.add_exception_handler(Exception, generic_exception_handler)

    @test_app.get("/provider-unavailable")
    async def provider_unavailable_route() -> None:
        raise ProviderUnavailableError("test message")

    @test_app.get("/namespace-violation")
    async def namespace_violation_route() -> None:
        raise NamespaceViolationError("namespace test")

    @test_app.get("/rate-limit")
    async def rate_limit_route() -> None:
        raise RateLimitError("rate test")

    @test_app.get("/runtime-error")
    async def runtime_error_route() -> None:
        raise RuntimeError("unexpected boom")

    return test_app


client = TestClient(make_test_app(), raise_server_exceptions=False)


def test_provider_unavailable_returns_503() -> None:
    response = client.get("/provider-unavailable")
    assert response.status_code == 503
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert body["error"]["message"] == "test message"
    assert "detail" not in body
    assert "request_id" in body["error"]


def test_provider_unavailable_request_id_is_uuid() -> None:
    response = client.get("/provider-unavailable")
    request_id = response.json()["error"]["request_id"]
    assert UUID_PATTERN.match(request_id), f"Expected UUID, got: {request_id}"


def test_namespace_violation_returns_403() -> None:
    response = client.get("/namespace-violation")
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "NAMESPACE_VIOLATION"
    assert "detail" not in body


def test_rate_limit_returns_429() -> None:
    response = client.get("/rate-limit")
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "detail" not in body


def test_generic_exception_returns_500() -> None:
    response = client.get("/runtime-error")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert body["error"]["message"] == "An unexpected error occurred"
    assert "detail" not in body


def test_generic_exception_request_id_is_non_empty() -> None:
    response = client.get("/runtime-error")
    request_id = response.json()["error"]["request_id"]
    assert request_id and len(request_id) > 0


def test_error_envelope_shape_no_extra_keys() -> None:
    response = client.get("/provider-unavailable")
    error = response.json()["error"]
    assert set(error.keys()) == {"code", "message", "request_id"}


# --- Real app wiring tests ---
# These exercise the actual exception handler registration in app/main.py
# rather than a separately-constructed test app, so that a future omission
# or wrong order in create_app() would be caught.

def make_real_app_with_routes() -> FastAPI:
    @real_app.get("/test/provider-unavailable-real")
    async def _provider_unavailable() -> None:
        raise ProviderUnavailableError("real app test")

    @real_app.get("/test/runtime-error-real")
    async def _runtime_error() -> None:
        raise RuntimeError("real boom")

    return real_app


real_client = TestClient(make_real_app_with_routes(), raise_server_exceptions=False)


def test_real_app_truerag_handler_registered() -> None:
    response = real_client.get("/test/provider-unavailable-real")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert "detail" not in body


def test_real_app_generic_handler_registered() -> None:
    response = real_client.get("/test/runtime-error-real")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "detail" not in body
