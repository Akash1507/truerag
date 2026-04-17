from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.utils.observability import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health")
async def health_check() -> JSONResponse:
    logger.info("health_check", extra={"operation": "health_check"})
    return JSONResponse(content={"status": "ok"})
