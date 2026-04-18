from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import ErrorCode, TrueRAGError
from app.utils.observability import get_logger

logger = get_logger(__name__)


async def truerag_exception_handler(request: Request, exc: TrueRAGError) -> JSONResponse:
    request_id: str = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": {"code": exc.code.value, "message": exc.message, "request_id": request_id}
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id: str = getattr(request.state, "request_id", "unknown")
    logger.error(
        "unhandled_exception",
        extra={"operation": "unhandled_exception", "extra_data": {"error": str(exc)}},
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": ErrorCode.INTERNAL_SERVER_ERROR.value,
                "message": "An unexpected error occurred",
                "request_id": request_id,
            }
        },
    )
