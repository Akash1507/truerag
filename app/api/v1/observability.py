from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.utils.observability import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health")
async def health_check() -> JSONResponse:
    logger.info("health_check", extra={"operation": "health_check"})
    return JSONResponse(content={"status": "ok"})


@router.get("/ready")
async def readiness_check(request: Request) -> JSONResponse:
    settings = get_settings()
    logger.info("readiness_check_start", extra={"operation": "readiness_check"})

    # MongoDB
    try:
        await request.app.state.motor_client.admin.command("ping")
    except Exception as exc:
        raise ProviderUnavailableError(f"mongodb unavailable: {exc}") from exc

    # pgvector
    try:
        await request.app.state.pg_pool.fetchval("SELECT 1")
    except Exception as exc:
        raise ProviderUnavailableError(f"pgvector unavailable: {exc}") from exc

    # SQS
    try:
        async with request.app.state.aws_session.client(
            "sqs", region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url
        ) as sqs:
            await sqs.get_queue_attributes(
                QueueUrl=settings.sqs_ingestion_queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
    except Exception as exc:
        raise ProviderUnavailableError(f"sqs unavailable: {exc}") from exc

    # DynamoDB
    try:
        async with request.app.state.aws_session.client(
            "dynamodb", region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url
        ) as dynamodb:
            await dynamodb.describe_table(TableName=settings.dynamodb_audit_table)
    except Exception as exc:
        raise ProviderUnavailableError(f"dynamodb unavailable: {exc}") from exc

    # S3
    try:
        async with request.app.state.aws_session.client(
            "s3", region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url
        ) as s3:
            await s3.head_bucket(Bucket=settings.s3_document_bucket)
    except Exception as exc:
        raise ProviderUnavailableError(f"s3 unavailable: {exc}") from exc

    logger.info(
        "readiness_check_ok",
        extra={"operation": "readiness_check", "extra_data": {"result": "ok"}},
    )
    return JSONResponse(
        content={"mongodb": "ok", "pgvector": "ok", "sqs": "ok", "dynamodb": "ok", "s3": "ok"}
    )
