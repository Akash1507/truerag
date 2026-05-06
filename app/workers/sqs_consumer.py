import asyncio
import json
from collections.abc import Mapping

import aioboto3

from app.core.config import Settings, get_settings
from app.core.errors import PermanentIngestionError
from app.db.dao.document_dao import document_dao
from app.db.dao.ingestion_job_dao import ingestion_job_dao
from app.interfaces.queue_backend import QueueBackend, QueueMessage
from app.models.ingestion_job import IngestionJobPayload
from app.providers.queue import get_queue_backend
from app.providers.queue.sqs_backend import SQSBackend
from app.utils.observability import get_logger
from app.workers.ingestion_worker import process_job

logger = get_logger(__name__)

MAX_RECEIVE_COUNT: int = 3


async def run_consumer(
    backend: QueueBackend,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    logger.info(
        "SQS consumer started",
        extra={
            "extra_data": {
                "queue": settings.sqs_ingestion_queue_url,
                "backend": backend.__class__.__name__,
            }
        },
    )
    while True:
        messages = await backend.receive(max_messages=1, wait_seconds=20)
        for msg in messages:
            await _dispatch(msg, backend, settings, aws_session)


async def _dispatch(
    msg: QueueMessage | Mapping[str, object],
    backend_or_session: QueueBackend | aioboto3.Session,
    settings: Settings,
    aws_session: aioboto3.Session | None = None,
) -> None:
    queue_message, backend, session = _normalize_dispatch_input(
        msg=msg,
        backend_or_session=backend_or_session,
        settings=settings,
        aws_session=aws_session,
    )
    body = queue_message.body
    payload = IngestionJobPayload(
        job_id=str(body["job_id"]),
        tenant_id=str(body["tenant_id"]),
        agent_id=str(body["agent_id"]),
        document_id=str(body["document_id"]),
        s3_key=str(body["s3_key"]),
        file_type=str(body["file_type"]),
        timestamp=str(body["timestamp"]),
    )
    receive_count = queue_message.receive_count

    try:
        await process_job(payload, session, settings)
        await backend.delete(queue_message.receipt_handle)
    except PermanentIngestionError as exc:
        logger.error(
            "permanent ingestion failure — deleting message",
            extra={"extra_data": {"job_id": payload.job_id, "error": str(exc)}},
        )
        try:
            await _update_status(
                job_id=payload.job_id,
                document_id=payload.document_id,
                status="failed",
                error_reason=str(exc),
            )
        except Exception as status_exc:
                logger.error(
                    "status_update_failed",
                    extra={"extra_data": {"job_id": payload.job_id, "error": str(status_exc)}},
                )
        await backend.delete(queue_message.receipt_handle)
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
            try:
                await _update_status(
                    job_id=payload.job_id,
                    document_id=payload.document_id,
                    status="failed",
                    error_reason=str(exc),
                )
            except Exception as status_exc:
                logger.error(
                    "status_update_failed",
                    extra={"extra_data": {"job_id": payload.job_id, "error": str(status_exc)}},
                )
            await backend.delete(queue_message.receipt_handle)


def _normalize_dispatch_input(
    msg: QueueMessage | Mapping[str, object],
    backend_or_session: QueueBackend | aioboto3.Session,
    settings: Settings,
    aws_session: aioboto3.Session | None,
) -> tuple[QueueMessage, QueueBackend, aioboto3.Session]:
    if isinstance(backend_or_session, QueueBackend):
        if aws_session is None:
            raise ValueError("aws_session must be provided when backend is passed to _dispatch")
        backend = backend_or_session
        session = aws_session
    else:
        session = backend_or_session
        backend = SQSBackend(aws_session=session, settings=settings)

    if isinstance(msg, QueueMessage):
        queue_message = msg
    else:
        queue_message = _queue_message_from_sqs_payload(msg)
    return queue_message, backend, session


def _queue_message_from_sqs_payload(msg: Mapping[str, object]) -> QueueMessage:
    raw_body = msg.get("Body")
    body: dict[str, object]
    if isinstance(raw_body, str):
        parsed = json.loads(raw_body)
        body = parsed if isinstance(parsed, dict) else {}
    elif isinstance(raw_body, (bytes, bytearray)):
        parsed = json.loads(raw_body.decode())
        body = parsed if isinstance(parsed, dict) else {}
    else:
        body = {}

    raw_attributes = msg.get("Attributes")
    attributes = raw_attributes if isinstance(raw_attributes, Mapping) else {}
    raw_receive_count = attributes.get("ApproximateReceiveCount", "1")
    receive_count = int(raw_receive_count) if isinstance(raw_receive_count, str) else 1

    return QueueMessage(
        message_id=str(msg.get("MessageId", "")),
        body=body,
        receipt_handle=str(msg.get("ReceiptHandle", "")),
        receive_count=receive_count,
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
        from beanie import init_beanie
        from motor.motor_asyncio import AsyncIOMotorClient

        from app.models.agent import AgentDocument
        from app.models.document import DocumentRecord
        from app.models.ingestion_job import IngestionJob
        from app.models.tenant import TenantDocument

        settings = get_settings()
        motor_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
        try:
            db = motor_client[settings.mongodb_database]
            await init_beanie(
                database=db,
                document_models=[TenantDocument, AgentDocument, DocumentRecord, IngestionJob],
            )
            session = aioboto3.Session()
            backend = get_queue_backend(settings=settings, aws_session=session)
            await run_consumer(backend, session, settings)
        finally:
            motor_client.close()

    asyncio.run(_main())
