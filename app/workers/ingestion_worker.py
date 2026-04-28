from dataclasses import dataclass
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings
from app.utils.observability import get_logger

logger = get_logger(__name__)


@dataclass
class IngestionJobPayload:
    job_id: str
    tenant_id: str
    agent_id: str
    document_id: str
    s3_key: str
    file_type: str
    timestamp: str


async def process_job(
    payload: IngestionJobPayload,
    db: AsyncIOMotorDatabase[Any],
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    await db["documents"].update_one(
        {"document_id": payload.document_id},
        {"$set": {"status": "processing"}},
    )
    async with aws_session.client(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as dynamo:
        await dynamo.update_item(
            TableName=settings.dynamodb_jobs_table,
            Key={"job_id": {"S": payload.job_id}},
            UpdateExpression="SET #st = :st",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":st": {"S": "processing"}},
        )

    await _run_pipeline_stub(payload, aws_session, settings)

    await db["documents"].update_one(
        {"document_id": payload.document_id},
        {"$set": {"status": "ready"}},
    )
    async with aws_session.client(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as dynamo:
        await dynamo.update_item(
            TableName=settings.dynamodb_jobs_table,
            Key={"job_id": {"S": payload.job_id}},
            UpdateExpression="SET #st = :st",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":st": {"S": "ready"}},
        )


async def _run_pipeline_stub(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    logger.info(
        "pipeline not yet implemented for Epic 4",
        extra={
            "extra_data": {
                "job_id": payload.job_id,
                "document_id": payload.document_id,
                "tenant_id": payload.tenant_id,
            }
        },
    )
