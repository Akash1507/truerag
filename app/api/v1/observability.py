from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.services.metrics_service import METRICS_CONTENT_TYPE, metrics_service
from app.utils.observability import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health")
async def health_check() -> JSONResponse:
    logger.info("health_check", extra={"operation": "health_check"})
    return JSONResponse(content={"status": "ok"})


@router.get("/ready")
async def readiness_check(request: Request) -> JSONResponse:
    logger.info("readiness_check_start", extra={"operation": "readiness_check"})
    readiness = await metrics_service.readiness_check(request)

    logger.info(
        "readiness_check_ok",
        extra={"operation": "readiness_check", "extra_data": {"result": "ok"}},
    )
    return JSONResponse(content=readiness)


@router.get("/metrics")
async def metrics_endpoint() -> Response:
    return Response(
        content=metrics_service.generate_metrics_text(),
        media_type=METRICS_CONTENT_TYPE,
    )


@router.get("/metrics/costs")
async def metrics_costs_endpoint(window_hours: int = 24) -> JSONResponse:
    costs = await metrics_service.get_cost_breakdown(time_window_hours=window_hours)
    return JSONResponse(content={"window_hours": window_hours, "costs": costs})
