import asyncio
import json
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings, get_settings
from app.core.errors import PermanentIngestionError
from app.utils.observability import get_logger
from app.workers.ingestion_worker import IngestionJobPayload, process_job

logger = get_logger(__name__)

MAX_RECEIVE_COUNT: int = 3


async def run_consumer(
    aws_session: aioboto3.Session,
    db: AsyncIOMotorDatabase[Any],
    settings: Settings,
) -> None:
    logger.info(
        "SQS consumer started",
        extra={"extra_data": {"queue": settings.sqs_ingestion_queue_url}},
    )
    while True:
        async with aws_session.client(
            "sqs",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as sqs:
            response = await sqs.receive_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                AttributeNames=["ApproximateReceiveCount"],
            )
        for msg in response.get("Messages", []):
            await _dispatch(msg, aws_session, db, settings)


async def _dispatch(
    msg: dict[str, Any],
    aws_session: aioboto3.Session,
    db: AsyncIOMotorDatabase[Any],
    settings: Settings,
) -> None:
    body = json.loads(msg["Body"])
    payload = IngestionJobPayload(
        job_id=body["job_id"],
        tenant_id=body["tenant_id"],
        agent_id=body["agent_id"],
        document_id=body["document_id"],
        s3_key=body["s3_key"],
        file_type=body["file_type"],
        timestamp=body["timestamp"],
    )
    receive_count = int(msg["Attributes"]["ApproximateReceiveCount"])

    try:
        await process_job(payload, db, aws_session, settings)
        async with aws_session.client(
            "sqs",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as sqs:
            await sqs.delete_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                ReceiptHandle=msg["ReceiptHandle"],
            )
    except PermanentIngestionError as exc:
        logger.error(
            "permanent ingestion failure — deleting message",
            extra={"extra_data": {"job_id": payload.job_id, "error": str(exc)}},
        )
        await _update_status(
            job_id=payload.job_id,
            document_id=payload.document_id,
            status="failed",
            error_reason=str(exc),
            db=db,
            aws_session=aws_session,
            settings=settings,
        )
        async with aws_session.client(
            "sqs",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as sqs:
            await sqs.delete_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                ReceiptHandle=msg["ReceiptHandle"],
            )
    except Exception as exc:
        logger.error(
            "transient ingestion failure",
            extra={
                "extra_data": {
                    "job_id": payload.job_id,
                    "receive_count": receive_count,
                    "error": str(exc),
                }
            },
        )
        if receive_count >= MAX_RECEIVE_COUNT:
            await _update_status(
                job_id=payload.job_id,
                document_id=payload.document_id,
                status="failed",
                error_reason=str(exc),
                db=db,
                aws_session=aws_session,
                settings=settings,
            )


async def _update_status(
    job_id: str,
    document_id: str,
    status: str,
    error_reason: str | None,
    db: AsyncIOMotorDatabase[Any],
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    mongo_update: dict[str, str] = {"status": status}
    if error_reason is not None:
        mongo_update["error_reason"] = error_reason

    await db["documents"].update_one(
        {"document_id": document_id},
        {"$set": mongo_update},
    )

    if error_reason is not None:
        update_expr = "SET #st = :st, error_reason = :er"
        expr_values: dict[str, Any] = {":st": {"S": status}, ":er": {"S": error_reason}}
    else:
        update_expr = "SET #st = :st"
        expr_values = {":st": {"S": status}}

    async with aws_session.client(
        "dynamodb",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as dynamo:
        await dynamo.update_item(
            TableName=settings.dynamodb_jobs_table,
            Key={"job_id": {"S": job_id}},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues=expr_values,
        )


if __name__ == "__main__":
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _main() -> None:
        settings = get_settings()
        db: AsyncIOMotorDatabase[Any] = AsyncIOMotorClient(settings.mongodb_uri)[
            settings.mongodb_database
        ]
        session = aioboto3.Session()
        await run_consumer(session, db, settings)

    asyncio.run(_main())
