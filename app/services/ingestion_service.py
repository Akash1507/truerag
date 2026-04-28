import json
from datetime import UTC, datetime
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from bson import ObjectId
from fastapi import UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings
from app.core.errors import IngestionError, UnsupportedFileTypeError
from app.models.document import DocumentUploadResponse
from app.services import agent_service
from app.utils.observability import get_logger

logger = get_logger(__name__)

SUPPORTED_FILE_TYPES: frozenset[str] = frozenset({"pdf", "txt", "md", "docx"})
MAX_UPLOAD_SIZE_BYTES: int = 50 * 1024 * 1024


async def upload_document(
    file: UploadFile,
    agent_id: str,
    tenant_id: str,
    db: AsyncIOMotorDatabase[Any],
    aws_session: aioboto3.Session,
    settings: Settings,
) -> DocumentUploadResponse:
    # Validate agent ownership — raises AgentNotFoundError (404) or ForbiddenError (403)
    await agent_service.get_agent(agent_id, tenant_id, db)

    # Validate file type from extension
    filename: str = file.filename or ""
    file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if file_ext not in SUPPORTED_FILE_TYPES:
        raise UnsupportedFileTypeError(
            f"Unsupported file type: {file_ext!r}. Supported: {sorted(SUPPORTED_FILE_TYPES)}"
        )

    document_id = str(ObjectId())
    job_id = str(ObjectId())
    now = datetime.now(UTC)
    s3_key = f"{tenant_id}/{agent_id}/{document_id}/{filename}"

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise IngestionError(
            f"File size {len(content)} bytes exceeds the"
            f" {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB limit",
            http_status=413,
        )

    # 1. Archive to S3 — failure propagates as 500 before any writes
    async with aws_session.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    ) as s3:
        await s3.put_object(
            Bucket=settings.s3_document_bucket,
            Key=s3_key,
            Body=content,
        )

    # 2. Insert MongoDB document record — compensate S3 on failure
    try:
        await db["documents"].insert_one(
            {
                "document_id": document_id,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "filename": filename,
                "file_type": file_ext,
                "s3_key": s3_key,
                "job_id": job_id,
                "status": "queued",
                "error_reason": None,
                "created_at": now,
            }
        )
    except Exception as exc:
        async with aws_session.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as s3:
            await s3.delete_object(Bucket=settings.s3_document_bucket, Key=s3_key)
        raise IngestionError(f"Failed to record document: {exc}") from exc

    # 3. Insert DynamoDB job record — compensate S3 + Mongo on failure
    try:
        async with aws_session.client(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as dynamo:
            await dynamo.put_item(
                TableName=settings.dynamodb_jobs_table,
                Item={
                    "job_id": {"S": job_id},
                    "document_id": {"S": document_id},
                    "status": {"S": "queued"},
                },
            )
    except Exception as exc:
        async with aws_session.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as s3:
            await s3.delete_object(Bucket=settings.s3_document_bucket, Key=s3_key)
        await db["documents"].delete_one({"document_id": document_id})
        raise IngestionError(f"Failed to create ingestion job: {exc}") from exc

    # 4. Enqueue SQS message — failure rolls status to failed on both stores
    try:
        async with aws_session.client(
            "sqs",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as sqs:
            await sqs.send_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                MessageBody=json.dumps(
                    {
                        "job_id": job_id,
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "document_id": document_id,
                        "s3_key": s3_key,
                        "file_type": file_ext,
                        "timestamp": now.isoformat(),
                    }
                ),
            )
    except Exception as sqs_exc:
        error_reason = str(sqs_exc)
        await db["documents"].update_one(
            {"document_id": document_id},
            {"$set": {"status": "failed", "error_reason": error_reason}},
        )
        async with aws_session.client(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as dynamo:
            await dynamo.update_item(
                TableName=settings.dynamodb_jobs_table,
                Key={"job_id": {"S": job_id}},
                UpdateExpression="SET #st = :st, error_reason = :er",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":st": {"S": "failed"},
                    ":er": {"S": error_reason},
                },
            )
        logger.error(
            "sqs_enqueue_failed",
            extra={
                "operation": "upload_document",
                "extra_data": {
                    "document_id": document_id,
                    "agent_id": agent_id,
                    "tenant_id": tenant_id,
                    "error": error_reason,
                },
            },
        )
        raise IngestionError(f"SQS enqueue failed: {sqs_exc}") from sqs_exc

    logger.info(
        "document_uploaded",
        extra={
            "operation": "upload_document",
            "extra_data": {
                "document_id": document_id,
                "job_id": job_id,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "file_type": file_ext,
            },
        },
    )

    return DocumentUploadResponse(
        job_id=job_id, document_id=document_id, status="queued"
    )
