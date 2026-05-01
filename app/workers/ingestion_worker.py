from datetime import UTC, datetime

import aioboto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.dependencies import get_vector_store
from app.core.errors import PermanentIngestionError
from app.db.dao.agent_dao import agent_dao
from app.db.dao.document_dao import document_dao
from app.db.dao.ingestion_job_dao import ingestion_job_dao
from app.models.document import DocumentStatus
from app.models.ingestion_job import IngestionJobPayload
from app.pipelines.ingestion.pipeline import run_ingestion_pipeline
from app.utils import semantic_cache
from app.utils.observability import get_logger

logger = get_logger(__name__)


async def process_job(
    payload: IngestionJobPayload,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    await document_dao.update(
        {"document_id": payload.document_id},
        {"status": DocumentStatus.processing},
    )
    await ingestion_job_dao.update(
        {"job_id": payload.job_id}, {"status": DocumentStatus.processing}
    )

    try:
        agent = await agent_dao.find_one(
            {"agent_id": payload.agent_id, "tenant_id": payload.tenant_id}
        )
        if agent is None:
            raise PermanentIngestionError("Agent not found — document cannot be retried")
        document = await document_dao.find_one({"document_id": payload.document_id})
        if document is None:
            raise PermanentIngestionError("Document not found — ingestion cannot continue")
        await run_ingestion_pipeline(
            payload,
            aws_session,
            settings,
            agent,
            document_version=document.version,
        )
        await _finalize_replacement_if_needed(document, payload, agent.vector_store)
    except PermanentIngestionError as exc:
        error_reason = str(exc)
        await ingestion_job_dao.update(
            {"job_id": payload.job_id},
            {"status": DocumentStatus.failed, "error_reason": error_reason},
        )
        await document_dao.update(
            {"document_id": payload.document_id},
            {"status": DocumentStatus.failed, "error_reason": error_reason},
        )
        raise
    except Exception as exc:
        error_reason = str(exc)
        await ingestion_job_dao.update(
            {"job_id": payload.job_id},
            {"status": DocumentStatus.failed, "error_reason": error_reason},
        )
        await document_dao.update(
            {"document_id": payload.document_id},
            {"status": DocumentStatus.failed, "error_reason": error_reason},
        )
        raise

    # Update job first (canonical status source in get_document_status)
    await ingestion_job_dao.update({"job_id": payload.job_id}, {"status": DocumentStatus.ready})
    await document_dao.update(
        {"document_id": payload.document_id},
        {"status": DocumentStatus.ready},
    )


async def _finalize_replacement_if_needed(
    document,
    payload: IngestionJobPayload,
    vector_store_name: str,
) -> None:
    if document.version <= 1:
        return

    predecessor = await document_dao.find_one(
        {
            "tenant_id": payload.tenant_id,
            "agent_id": payload.agent_id,
            "lineage_id": document.lineage_id,
            "version": document.version - 1,
            "archived_at": None,
        }
    )
    if predecessor is None:
        return

    namespace = f"{payload.tenant_id}_{payload.agent_id}"
    vector_store = get_vector_store(vector_store_name)
    delete_document_fn = getattr(vector_store, "delete_document", None)
    if not callable(delete_document_fn):
        await _rollback_new_vectors(vector_store, namespace, payload.document_id)
        raise PermanentIngestionError(
            f"Vector store '{vector_store_name}' does not support document-scoped deletion"
        )
    try:
        await delete_document_fn(namespace, predecessor.document_id)
    except Exception:
        await _rollback_new_vectors(vector_store, namespace, payload.document_id)
        raise

    now = datetime.now(UTC)
    await document_dao.update(
        {"document_id": predecessor.document_id},
        {
            "archived_at": now,
            "superseded_by_document_id": payload.document_id,
        },
    )
    try:
        await semantic_cache.invalidate(payload.agent_id)
    except Exception:
        logger.exception(
            "semantic_cache_invalidation_failed",
            extra={
                "operation": "replacement_finalization",
                "extra_data": {
                    "agent_id": payload.agent_id,
                    "tenant_id": payload.tenant_id,
                    "document_id": payload.document_id,
                    "predecessor_document_id": predecessor.document_id,
                },
            },
        )


async def _rollback_new_vectors(vector_store, namespace: str, document_id: str) -> None:
    rollback_delete_document_fn = getattr(vector_store, "delete_document", None)
    if not callable(rollback_delete_document_fn):
        logger.error(
            "replacement_rollback_unsupported",
            extra={
                "operation": "replacement_finalization",
                "extra_data": {
                    "namespace": namespace,
                    "document_id": document_id,
                },
            },
        )
        return

    await rollback_delete_document_fn(namespace, document_id)
