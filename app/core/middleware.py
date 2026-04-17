import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.utils.observability import reset_request_context, set_request_context


class RequestIDMiddleware(BaseHTTPMiddleware):
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
