import json
import hashlib
from datetime import UTC, datetime

import aioboto3  # type: ignore[import-untyped]
from bson import ObjectId
from fastapi import UploadFile

from app.core.dependencies import get_vector_store
from app.core.config import Settings
from app.core.errors import (
    DocumentNotFoundError,
    ForbiddenError,
    IngestionError,
    ProviderUnavailableError,
    UnsupportedFileTypeError,
)
from app.db.dao.document_dao import document_dao
from app.db.dao.ingestion_job_dao import ingestion_job_dao
from app.models.document import (
    DocumentListItem,
    DocumentRecord,
    DocumentStatus,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.models.ingestion_job import IngestionJob
from app.services import agent_service
from app.utils.observability import get_logger
from app.utils.pagination import DEFAULT_PAGE_SIZE, decode_cursor, encode_cursor

logger = get_logger(__name__)

SUPPORTED_FILE_TYPES: frozenset[str] = frozenset({"pdf", "txt", "md", "docx"})
MAX_UPLOAD_SIZE_BYTES: int = 50 * 1024 * 1024


async def upload_document(
    file: UploadFile,
    agent_id: str,
    tenant_id: str,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> DocumentUploadResponse:
    # Validate agent ownership — raises AgentNotFoundError (404) or ForbiddenError (403)
    await agent_service.get_agent(agent_id, tenant_id)

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

    content_hash = hashlib.sha256(content).hexdigest()
    predecessor_candidates = await document_dao.find(
        {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "content_hash": content_hash,
            "archived_at": None,
            "status": DocumentStatus.ready,
        },
        sort=[("created_at", -1)],
        limit=1,
    )
    predecessor = predecessor_candidates[0] if predecessor_candidates else None
    if predecessor is None:
        version = 1
        lineage_id = document_id
    else:
        version = predecessor.version + 1
        lineage_id = predecessor.lineage_id or predecessor.document_id

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

    document_record = DocumentRecord(
        document_id=document_id,
        agent_id=agent_id,
        tenant_id=tenant_id,
        filename=filename,
        file_type=file_ext,
        s3_key=s3_key,
        job_id=job_id,
        version=version,
        content_hash=content_hash,
        lineage_id=lineage_id,
        archived_at=None,
        superseded_by_document_id=None,
        status=DocumentStatus.queued,
        error_reason=None,
        created_at=now,
    )
    try:
        await document_dao.insert_one(document_record)
    except Exception as exc:
        async with aws_session.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as s3:
            await s3.delete_object(Bucket=settings.s3_document_bucket, Key=s3_key)
        raise IngestionError(f"Failed to record document: {exc}") from exc

    try:
        await ingestion_job_dao.insert_one(
            IngestionJob(
                job_id=job_id,
                document_id=document_id,
                tenant_id=tenant_id,
                status=DocumentStatus.queued,
            )
        )
    except Exception as exc:
        async with aws_session.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as s3:
            await s3.delete_object(Bucket=settings.s3_document_bucket, Key=s3_key)
        try:
            await document_dao.delete_one({"document_id": document_id})
        except Exception as cleanup_exc:
            logger.error(
                "compensation_cleanup_failed",
                extra={
                    "operation": "upload_document",
                    "extra_data": {"document_id": document_id, "error": str(cleanup_exc)},
                },
            )
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
        await document_dao.update(
            {"document_id": document_id},
            {"status": DocumentStatus.failed, "error_reason": error_reason},
        )
        await ingestion_job_dao.update(
            {"job_id": job_id},
            {"status": "failed", "error_reason": error_reason},
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


async def get_document_status(
    document_id: str,
    agent_id: str,
    tenant_id: str,
) -> DocumentStatusResponse:
    doc = await document_dao.find_one({"document_id": document_id})
    if doc is None:
        raise DocumentNotFoundError(f"Document '{document_id}' not found")
    if doc.tenant_id != tenant_id or doc.agent_id != agent_id:
        raise ForbiddenError(f"Document '{document_id}' does not belong to this tenant/agent")

    job_id = doc.job_id
    if job_id is None:
        logger.info(
            "get_document_status",
            extra={
                "operation": "get_document_status",
                "extra_data": {
                    "document_id": document_id,
                    "agent_id": agent_id,
                    "tenant_id": tenant_id,
                },
            },
        )
        return DocumentStatusResponse(
            document_id=document_id,
            status=doc.status,
            error_reason=doc.error_reason,
        )

    job = await ingestion_job_dao.find_one({"job_id": job_id})
    if job is None:
        status_val = doc.status
        error_reason = doc.error_reason
    else:
        status_val = job.status
        error_reason = job.error_reason

    logger.info(
        "get_document_status",
        extra={
            "operation": "get_document_status",
            "extra_data": {
                "document_id": document_id,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
            },
        },
    )
    return DocumentStatusResponse(
        document_id=document_id,
        status=status_val,
        error_reason=error_reason,
    )


async def list_documents(
    agent_id: str,
    tenant_id: str,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[DocumentListItem], str | None]:
    await agent_service.get_agent(agent_id, tenant_id)

    query: dict[str, object] = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "archived_at": None,
    }
    if cursor:
        oid = decode_cursor(cursor)
        query["_id"] = {"$gt": oid}

    docs = await document_dao.find(query, sort=[("_id", 1)], limit=limit + 1)

    has_more = len(docs) > limit
    if has_more:
        docs = docs[:limit]

    next_cursor: str | None = encode_cursor(docs[-1].id) if has_more and docs and docs[-1].id else None
    items = [
        DocumentListItem(
            document_id=d.document_id,
            filename=d.filename,
            file_type=d.file_type,
            status=d.status,
            created_at=d.created_at,
        )
        for d in docs
    ]

    logger.debug(
        "list_documents",
        extra={
            "operation": "list_documents",
            "extra_data": {"count": len(items), "tenant_id": tenant_id, "agent_id": agent_id},
        },
    )
    return items, next_cursor


async def delete_document(
    document_id: str,
    agent_id: str,
    tenant_id: str,
) -> None:
    agent = await agent_service.get_agent(agent_id, tenant_id)

    doc = await document_dao.find_one({"document_id": document_id})
    if doc is None:
        raise DocumentNotFoundError(f"Document '{document_id}' not found")
    if doc.tenant_id != tenant_id or doc.agent_id != agent_id:
        raise ForbiddenError(f"Document '{document_id}' does not belong to this tenant/agent")

    namespace = f"{tenant_id}_{agent_id}"
    vector_store = get_vector_store(agent.vector_store)
    delete_document_fn = getattr(vector_store, "delete_document", None)
    if not callable(delete_document_fn):
        raise ProviderUnavailableError(
            f"Vector store '{agent.vector_store}' does not support document-scoped deletion"
        )

    await delete_document_fn(namespace, document_id)
    if doc.job_id is not None:
        await ingestion_job_dao.delete_many({"job_id": doc.job_id, "tenant_id": tenant_id})
    else:
        await ingestion_job_dao.delete_many({"document_id": document_id, "tenant_id": tenant_id})
    await document_dao.delete_one(
        {
            "document_id": document_id,
            "agent_id": agent_id,
            "tenant_id": tenant_id,
        }
    )

    logger.info(
        "document_deleted",
        extra={
            "operation": "delete_document",
            "extra_data": {
                "document_id": document_id,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
            },
        },
    )
