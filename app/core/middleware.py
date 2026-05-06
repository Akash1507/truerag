import uuid
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.utils.observability import (
    get_logger,
    mask_sensitive,
    reset_request_context,
    set_request_context,
)

logger = get_logger(__name__)


class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):  # type: ignore[misc]
    _MASKED_HEADERS = frozenset({"authorization", "x-api-key"})

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = perf_counter()
        headers = {
            key: "***" if key.lower() in self._MASKED_HEADERS else value
            for key, value in request.headers.items()
        }
        logger.bind(operation="http_request").info(
            "http_request",
            method=request.method,
            path=request.url.path,
            headers=mask_sensitive(headers),
        )
        response = await call_next(request)
        latency_ms = int((perf_counter() - start) * 1000)
        logger.bind(operation="http_response", latency_ms=latency_ms).info(
            "http_response",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):  # type: ignore[misc]
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        tokens = set_request_context(request_id=request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            reset_request_context(tokens)
        response.headers["X-Request-ID"] = request_id
        return response
