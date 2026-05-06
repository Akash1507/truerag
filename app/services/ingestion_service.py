import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import aioboto3  # type: ignore[import-untyped]
from bson import ObjectId
from fastapi import UploadFile

from app.core.config import Settings
from app.core.dependencies import get_vector_store
from app.core.errors import (
    DocumentNotFoundError,
    ForbiddenError,
    IngestionError,
    InvalidCursorError,
    ProviderUnavailableError,
    TrueRAGError,
    UnsupportedFileTypeError,
)
from app.db.dao.agent_dao import AgentDAO, agent_dao
from app.db.dao.document_dao import DocumentDAO, document_dao
from app.db.dao.ingestion_job_dao import IngestionJobDAO, ingestion_job_dao
from app.interfaces.queue_backend import QueueBackend
from app.models.document import (
    DocumentListItem,
    DocumentListResponse,
    DocumentRecord,
    DocumentStatus,
    DocumentStatusResponse,
    DocumentUploadResponse,
    ReindexResponse,
)
from app.models.ingestion_job import IngestionJob
from app.providers.queue import get_queue_backend
from app.services.agent_service import AgentService, agent_service
from app.utils import semantic_cache
from app.utils.observability import get_logger
from app.utils.pagination import DEFAULT_PAGE_SIZE, decode_cursor, encode_cursor

logger = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

try:
    from app.core.decorators import service_method  # type: ignore[import-not-found]
except Exception:
    def service_method(
        operation: str,
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                try:
                    return await func(*args, **kwargs)
                except TrueRAGError:
                    raise
                except ValueError as exc:
                    raise InvalidCursorError(str(exc)) from exc
                except Exception:
                    logger.exception(
                        "service_method_error",
                        extra={
                            "operation": operation,
                            "extra_data": {"service": "ingestion_service"},
                        },
                    )
                    raise

            return wrapper

        return decorator


SUPPORTED_FILE_TYPES: frozenset[str] = frozenset({"pdf", "txt", "md", "docx"})
MAX_UPLOAD_SIZE_BYTES: int = 50 * 1024 * 1024


class IngestionService:
    def __init__(
        self,
        document_dao_dep: DocumentDAO,
        ingestion_job_dao_dep: IngestionJobDAO,
        agent_dao_dep: AgentDAO,
        agent_service_dep: AgentService,
        vector_store_getter: Callable[[str], Any] = get_vector_store,
        queue_backend_getter: Callable[[Settings, aioboto3.Session | None], QueueBackend] = (
            get_queue_backend
        ),
    ) -> None:
        self._document_dao = document_dao_dep
        self._ingestion_job_dao = ingestion_job_dao_dep
        self._agent_dao = agent_dao_dep
        self._agent_service = agent_service_dep
        self._vector_store_getter = vector_store_getter
        self._queue_backend_getter = queue_backend_getter

    def _get_queue_backend(self, settings: Settings, aws_session: aioboto3.Session) -> QueueBackend:
        return self._queue_backend_getter(settings, aws_session)

    async def _list_documents_legacy(
        self,
        agent_id: str,
        tenant_id: str,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[DocumentListItem], str | None]:
        await self._agent_service.get_agent(agent_id, tenant_id)

        query: dict[str, object] = {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "archived_at": None,
        }
        if cursor:
            oid = decode_cursor(cursor)
            query["_id"] = {"$gt": oid}

        docs = await self._document_dao.find(query, sort=[("_id", 1)], limit=limit + 1)

        has_more = len(docs) > limit
        if has_more:
            docs = docs[:limit]

        next_cursor: str | None = (
            encode_cursor(docs[-1].id) if has_more and docs and docs[-1].id else None
        )
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
        return items, next_cursor

    @service_method("upload_document")
    async def upload_document(
        self,
        file: UploadFile,
        agent_id: str,
        tenant_id: str,
        aws_session: aioboto3.Session,
        settings: Settings,
    ) -> DocumentUploadResponse:
        await self._agent_service.get_agent(agent_id, tenant_id)

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
        predecessor_candidates = await self._document_dao.find(
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
            await self._document_dao.insert_one(document_record)
        except Exception as exc:
            async with aws_session.client(
                "s3",
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            ) as s3:
                await s3.delete_object(Bucket=settings.s3_document_bucket, Key=s3_key)
            raise IngestionError(f"Failed to record document: {exc}") from exc

        try:
            await self._ingestion_job_dao.insert_one(
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
                await self._document_dao.delete_one({"document_id": document_id})
            except Exception as cleanup_exc:
                logger.error(
                    "compensation_cleanup_failed",
                    extra={
                        "operation": "upload_document",
                        "extra_data": {"document_id": document_id, "error": str(cleanup_exc)},
                    },
                )
            raise IngestionError(f"Failed to create ingestion job: {exc}") from exc

        payload: dict[str, object] = {
            "job_id": job_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "document_id": document_id,
            "s3_key": s3_key,
            "file_type": file_ext,
            "timestamp": now.isoformat(),
        }
        queue_backend = self._get_queue_backend(settings, aws_session)
        try:
            await queue_backend.send(payload)
        except Exception as enqueue_exc:
            error_reason = str(enqueue_exc)
            await self._document_dao.update(
                {"document_id": document_id},
                {"status": DocumentStatus.failed, "error_reason": error_reason},
            )
            await self._ingestion_job_dao.update(
                {"job_id": job_id},
                {"status": "failed", "error_reason": error_reason},
            )
            logger.error(
                "queue_enqueue_failed",
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
            raise IngestionError(f"Queue enqueue failed: {enqueue_exc}") from enqueue_exc

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

        return DocumentUploadResponse(job_id=job_id, document_id=document_id, status="queued")

    @service_method("get_document_status")
    async def get_document_status(
        self,
        document_id: str,
        agent_id: str,
        tenant_id: str,
    ) -> DocumentStatusResponse:
        doc = await self._document_dao.find_one({"document_id": document_id})
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

        job = await self._ingestion_job_dao.find_one({"job_id": job_id})
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

    @service_method("list_documents")
    async def list_documents(
        self,
        agent_id: str,
        tenant_id: str,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> DocumentListResponse:
        items, next_cursor = await self._list_documents_legacy(agent_id, tenant_id, cursor, limit)
        logger.debug(
            "list_documents",
            extra={
                "operation": "list_documents",
                "extra_data": {"count": len(items), "tenant_id": tenant_id, "agent_id": agent_id},
            },
        )
        return DocumentListResponse(items=items, next_cursor=next_cursor)

    @service_method("delete_document")
    async def delete_document(
        self,
        document_id: str,
        agent_id: str,
        tenant_id: str,
    ) -> None:
        agent = await self._agent_service.get_agent(agent_id, tenant_id)

        doc = await self._document_dao.find_one({"document_id": document_id})
        if doc is None:
            raise DocumentNotFoundError(f"Document '{document_id}' not found")
        if doc.tenant_id != tenant_id or doc.agent_id != agent_id:
            raise ForbiddenError(f"Document '{document_id}' does not belong to this tenant/agent")

        namespace = f"{tenant_id}_{agent_id}"
        vector_store = self._vector_store_getter(agent.vector_store)
        delete_document_fn = getattr(vector_store, "delete_document", None)
        if not callable(delete_document_fn):
            raise ProviderUnavailableError(
                f"Vector store '{agent.vector_store}' does not support document-scoped deletion"
            )

        await delete_document_fn(namespace, document_id)
        await self._ingestion_job_dao.delete_many({"document_id": document_id, "tenant_id": tenant_id})
        await self._document_dao.delete_one(
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

    @service_method("reindex_agent")
    async def reindex_agent(
        self,
        agent_id: str,
        tenant_id: str,
        aws_session: aioboto3.Session,
        settings: Settings,
    ) -> ReindexResponse:
        agent = await self._agent_service.get_agent(agent_id, tenant_id)
        namespace = f"{tenant_id}_{agent_id}"
        now = datetime.now(UTC)

        await semantic_cache.invalidate(agent_id)

        vector_store = self._vector_store_getter(agent.vector_store)
        await vector_store.delete_namespace(namespace)

        docs = await self._document_dao.find(
            {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "status": DocumentStatus.ready,
                "archived_at": None,
            }
        )
        queued_docs: list[tuple[DocumentRecord, str]] = []

        for doc in docs:
            new_job_id = str(ObjectId())
            await self._ingestion_job_dao.insert_one(
                IngestionJob(
                    job_id=new_job_id,
                    document_id=doc.document_id,
                    tenant_id=tenant_id,
                    status=DocumentStatus.queued,
                )
            )
            await self._document_dao.update(
                {"document_id": doc.document_id},
                {"status": DocumentStatus.queued, "job_id": new_job_id, "error_reason": None},
            )
            queued_docs.append((doc, new_job_id))

        queue_backend = self._get_queue_backend(settings, aws_session)
        for index, (doc, new_job_id) in enumerate(queued_docs):
            payload: dict[str, object] = {
                "job_id": new_job_id,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "document_id": doc.document_id,
                "s3_key": doc.s3_key,
                "file_type": doc.file_type,
                "timestamp": now.isoformat(),
            }
            try:
                await queue_backend.send(payload)
            except Exception as enqueue_exc:
                failed_docs = queued_docs[index:]
                error_reason = str(enqueue_exc)
                for failed_doc, failed_job_id in failed_docs:
                    await self._document_dao.update(
                        {"document_id": failed_doc.document_id},
                        {
                            "status": DocumentStatus.failed,
                            "job_id": failed_job_id,
                            "error_reason": error_reason,
                        },
                    )
                    await self._ingestion_job_dao.update(
                        {"job_id": failed_job_id},
                        {"status": DocumentStatus.failed, "error_reason": error_reason},
                    )
                logger.error(
                    "reindex_enqueue_failed",
                    extra={
                        "operation": "reindex_agent",
                        "extra_data": {
                            "tenant_id": tenant_id,
                            "agent_id": agent_id,
                            "failed_document_id": doc.document_id,
                            "failed_count": len(failed_docs),
                            "error": error_reason,
                        },
                    },
                )
                raise IngestionError(f"Queue enqueue failed during reindex: {enqueue_exc}") from enqueue_exc

        await self._agent_dao.update(
            {"agent_id": agent_id},
            {"embedding_provider_mismatch": False, "updated_at": datetime.now(UTC)},
        )

        logger.info(
            "reindex_complete",
            extra={
                "operation": "reindex_agent",
                "extra_data": {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "enqueued_count": len(docs),
                },
            },
        )
        return ReindexResponse(enqueued_count=len(docs))


ingestion_service = IngestionService(
    document_dao_dep=document_dao,
    ingestion_job_dao_dep=ingestion_job_dao,
    agent_dao_dep=agent_dao,
    agent_service_dep=agent_service,
)


# Legacy compatibility wrappers for non-story call sites.
async def upload_document(
    file: UploadFile,
    agent_id: str,
    tenant_id: str,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> DocumentUploadResponse:
    return await ingestion_service.upload_document(file, agent_id, tenant_id, aws_session, settings)


async def get_document_status(
    document_id: str,
    agent_id: str,
    tenant_id: str,
) -> DocumentStatusResponse:
    return await ingestion_service.get_document_status(document_id, agent_id, tenant_id)


async def list_documents(
    agent_id: str,
    tenant_id: str,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[DocumentListItem], str | None]:
    return await ingestion_service._list_documents_legacy(agent_id, tenant_id, cursor, limit)


async def delete_document(
    document_id: str,
    agent_id: str,
    tenant_id: str,
) -> None:
    await ingestion_service.delete_document(document_id, agent_id, tenant_id)


async def reindex_agent(
    agent_id: str,
    tenant_id: str,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> ReindexResponse:
    return await ingestion_service.reindex_agent(agent_id, tenant_id, aws_session, settings)
