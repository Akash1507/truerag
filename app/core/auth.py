import hashlib
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import AuthenticationError, ErrorCode, NamespaceViolationError
from app.models.tenant import TenantDocument
from app.utils.observability import get_logger

logger = get_logger(__name__)

SKIP_AUTH_PATHS: frozenset[str] = frozenset({
    "/v1/health",
    "/v1/ready",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
})

SKIP_AUTH_METHOD_PATHS: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/v1/tenants"),
})


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _auth_error(
    status_code: int, code: ErrorCode, message: str, request_id: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": str(code), "message": message, "request_id": request_id}},
    )


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Normalize trailing slash so /v1/health/ matches /v1/health
        path = request.url.path.rstrip("/") or "/"
        if path in SKIP_AUTH_PATHS or (request.method, path) in SKIP_AUTH_METHOD_PATHS:
            return await call_next(request)

        request_id: str = getattr(request.state, "request_id", "unknown")
        raw_key = request.headers.get("X-API-Key", "").strip() or None

        if not raw_key:
            logger.warning(
                "auth_missing_key",
                extra={"operation": "authenticate", "extra_data": {"path": request.url.path}},
            )
            return _auth_error(401, ErrorCode.UNAUTHORIZED, "Missing X-API-Key header", request_id)

        key_hash = _hash_api_key(raw_key)
        settings = get_settings()
        motor_client: AsyncIOMotorClient[Any] = request.app.state.motor_client

        try:
            tenant_doc: dict[str, Any] | None = await motor_client[settings.mongodb_database][
                "tenants"
            ].find_one({"api_key_hash": key_hash})
        except Exception:
            logger.error(
                "auth_db_error",
                extra={"operation": "authenticate", "extra_data": {"path": request.url.path}},
            )
            return _auth_error(
                503,
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Authentication service unavailable",
                request_id,
            )

        if tenant_doc is None:
            logger.warning(
                "auth_invalid_key",
                extra={"operation": "authenticate", "extra_data": {"path": request.url.path}},
            )
            return _auth_error(401, ErrorCode.UNAUTHORIZED, "Invalid API key", request_id)

        try:
            tenant = TenantDocument.model_validate(tenant_doc)
        except ValidationError:
            logger.error(
                "auth_tenant_invalid",
                extra={"operation": "authenticate", "extra_data": {"path": request.url.path}},
            )
            return _auth_error(
                500, ErrorCode.INTERNAL_SERVER_ERROR, "Internal server error", request_id
            )

        request.state.tenant = tenant
        logger.info(
            "auth_ok",
            extra={
                "operation": "authenticate",
                "extra_data": {"tenant_id": tenant.tenant_id, "path": request.url.path},
            },
        )
        return await call_next(request)


def get_current_tenant(request: Request) -> TenantDocument:
    """FastAPI dependency — returns tenant resolved by AuthMiddleware."""
    if not hasattr(request.state, "tenant"):
        raise AuthenticationError()
    return request.state.tenant  # type: ignore[no-any-return]


def verify_tenant_ownership(authenticated_tenant_id: str, resource_tenant_id: str) -> None:
    if authenticated_tenant_id != resource_tenant_id:
        raise NamespaceViolationError("Cross-tenant access denied")
