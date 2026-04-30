import asyncio
import json

import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings, get_settings
from app.db.dao.document_dao import document_dao
from app.db.dao.ingestion_job_dao import ingestion_job_dao
from app.core.errors import PermanentIngestionError
from app.utils.observability import get_logger
from app.workers.ingestion_worker import IngestionJobPayload, process_job

logger = get_logger(__name__)

MAX_RECEIVE_COUNT: int = 3


async def run_consumer(
    aws_session: aioboto3.Session,
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
            await _dispatch(msg, aws_session, settings)


async def _dispatch(
    msg: dict[str, object],
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    body = json.loads(str(msg["Body"]))
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
        await process_job(payload, aws_session, settings)
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
            )


async def _update_status(
    job_id: str,
    document_id: str,
    status: str,
    error_reason: str | None,
) -> None:
    update_dict: dict[str, str] = {"status": status}
    if error_reason is not None:
        update_dict["error_reason"] = error_reason

    await document_dao.update({"document_id": document_id}, update_dict)
    await ingestion_job_dao.update({"job_id": job_id}, update_dict)


if __name__ == "__main__":
    async def _main() -> None:
        settings = get_settings()
        session = aioboto3.Session()
        await run_consumer(session, settings)

    asyncio.run(_main())
