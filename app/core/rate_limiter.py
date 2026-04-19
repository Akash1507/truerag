import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import ErrorCode
from app.models.tenant import TenantDocument
from app.utils.observability import get_logger

logger = get_logger(__name__)

# Module-level fixed-window store: tenant_id → (window_start, request_count)
_counters: dict[str, tuple[float, int]] = {}


def _rate_limit_error(request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": str(ErrorCode.RATE_LIMIT_EXCEEDED),
                "message": "Rate limit exceeded",
                "request_id": request_id,
            }
        },
    )


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not hasattr(request.state, "tenant"):
            return await call_next(request)

        tenant: TenantDocument = request.state.tenant
        request_id: str = getattr(request.state, "request_id", "unknown")
        settings = get_settings()
        limit = (
            tenant.rate_limit_rpm
            if tenant.rate_limit_rpm is not None and tenant.rate_limit_rpm > 0
            else settings.default_rate_limit_rpm
        )

        now = time.monotonic()
        entry = _counters.get(tenant.tenant_id)

        if entry is None or (now - entry[0]) >= 60.0:
            _counters[tenant.tenant_id] = (now, 1)
            logger.debug(
                "rate_limit_allowed",
                extra={"extra_data": {"tenant_id": tenant.tenant_id, "count": 1, "limit": limit}},
            )
            return await call_next(request)

        window_start, count = entry
        if count >= limit:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "operation": "rate_limit",
                    "extra_data": {"tenant_id": tenant.tenant_id, "limit": limit, "count": count},
                },
            )
            return _rate_limit_error(request_id)

        _counters[tenant.tenant_id] = (window_start, count + 1)
        logger.debug(
            "rate_limit_allowed",
            extra={
                "extra_data": {
                    "tenant_id": tenant.tenant_id,
                    "count": count + 1,
                    "limit": limit,
                }
            },
        )
        return await call_next(request)
