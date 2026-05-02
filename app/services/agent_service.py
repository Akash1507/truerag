from datetime import UTC, datetime

import aioboto3  # type: ignore[import-untyped]
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.dependencies import get_vector_store
from app.core.errors import (
    AgentAlreadyExistsError,
    AgentConfigInvalidError,
    AgentNotFoundError,
    ForbiddenError,
)
from app.db.dao.agent_dao import agent_dao
from app.db.dao.document_dao import document_dao
from app.db.dao.ingestion_job_dao import ingestion_job_dao
from app.models.agent import (
    VALID_CHUNKING_STRATEGIES,
    VALID_EMBEDDING_PROVIDERS,
    VALID_LLM_PROVIDERS,
    VALID_RERANKERS,
    VALID_RETRIEVAL_MODES,
    VALID_VECTOR_STORES,
    AgentConfigUpdateRequest,
    AgentCreateRequest,
    AgentDocument,
)
from app.utils.observability import get_logger
from app.utils.pagination import DEFAULT_PAGE_SIZE, decode_cursor, encode_cursor

logger = get_logger(__name__)

_FIELD_VALIDATORS: list[tuple[str, frozenset[str]]] = [
    ("chunking_strategy", VALID_CHUNKING_STRATEGIES),
    ("vector_store", VALID_VECTOR_STORES),
    ("embedding_provider", VALID_EMBEDDING_PROVIDERS),
    ("llm_provider", VALID_LLM_PROVIDERS),
    ("retrieval_mode", VALID_RETRIEVAL_MODES),
    ("reranker", VALID_RERANKERS),
]


async def create_agent(
    request: AgentCreateRequest,
    tenant_id: str,
) -> AgentDocument:
    if request.tenant_id is not None and request.tenant_id != tenant_id:
        raise ForbiddenError("Cannot create agent for a different tenant")

    for field, valid_set in _FIELD_VALIDATORS:
        value: str = getattr(request, field)
        if value not in valid_set:
            raise AgentConfigInvalidError(
                f"Invalid {field}: {value!r}. Supported values: {sorted(valid_set)}"
            )

    if request.semantic_cache_enabled and request.semantic_cache_threshold is None:
        raise AgentConfigInvalidError(
            "semantic_cache_threshold is required when semantic_cache_enabled is true"
        )

    existing = await agent_dao.find_one({"tenant_id": tenant_id, "name": request.name})
    if existing is not None:
        raise AgentAlreadyExistsError(
            f"Agent with name '{request.name}' already exists for this tenant"
        )

    agent_id = str(ObjectId())
    now = datetime.now(UTC)

    agent = AgentDocument(
        agent_id=agent_id,
        tenant_id=tenant_id,
        name=request.name,
        chunking_strategy=request.chunking_strategy,
        vector_store=request.vector_store,
        embedding_provider=request.embedding_provider,
        llm_provider=request.llm_provider,
        retrieval_mode=request.retrieval_mode,
        reranker=request.reranker,
        top_k=request.top_k,
        semantic_cache_enabled=request.semantic_cache_enabled,
        semantic_cache_threshold=request.semantic_cache_threshold,
        faithfulness_threshold=request.faithfulness_threshold,
        status="active",
        created_at=now,
        updated_at=now,
    )
    try:
        await agent_dao.insert_one(agent)
    except DuplicateKeyError as exc:
        raise AgentAlreadyExistsError(
            f"Agent with name '{request.name}' already exists for this tenant"
        ) from exc

    logger.info(
        "agent_created",
        extra={
            "operation": "create_agent",
            "extra_data": {"agent_id": agent_id, "tenant_id": tenant_id},
        },
    )

    return agent


async def get_agent(
    agent_id: str,
    tenant_id: str,
) -> AgentDocument:
    doc = await agent_dao.find_one({"agent_id": agent_id})
    if doc is None:
        raise AgentNotFoundError(f"Agent '{agent_id}' not found")
    if doc.tenant_id != tenant_id:
        raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")
    return doc


async def list_agents(
    tenant_id: str,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[AgentDocument], str | None]:
    query: dict[str, object] = {"tenant_id": tenant_id}
    if cursor:
        oid = decode_cursor(cursor)  # raises ValueError on invalid cursor — caught at route layer
        query["_id"] = {"$gt": oid}

    docs = await agent_dao.find(query, sort=[("_id", 1)], limit=limit + 1)

    has_more = len(docs) > limit
    if has_more:
        docs = docs[:limit]

    next_cursor: str | None = encode_cursor(docs[-1].id) if has_more and docs and docs[-1].id else None
    items = docs

    logger.debug(
        "list_agents",
        extra={
            "operation": "list_agents",
            "extra_data": {"count": len(items), "tenant_id": tenant_id},
        },
    )
    return items, next_cursor


async def update_agent_config(
    agent_id: str,
    tenant_id: str,
    request: AgentConfigUpdateRequest,
) -> tuple[AgentDocument, list[str]]:
    doc = await agent_dao.find_one({"agent_id": agent_id})
    if doc is None:
        raise AgentNotFoundError(f"Agent '{agent_id}' not found")
    if doc.tenant_id != tenant_id:
        raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")

    for field, valid_set in _FIELD_VALIDATORS:
        value: str | None = getattr(request, field)
        if value is not None and value not in valid_set:
            raise AgentConfigInvalidError(
                f"Invalid {field}: {value!r}. Supported values: {sorted(valid_set)}"
            )

    provided_fields = request.model_fields_set
    update_dict: dict[str, object] = {}
    for field in (
        "chunking_strategy",
        "vector_store",
        "embedding_provider",
        "llm_provider",
        "retrieval_mode",
        "reranker",
        "top_k",
        "semantic_cache_enabled",
        "semantic_cache_threshold",
        "faithfulness_threshold",
    ):
        if field in provided_fields:
            update_dict[field] = getattr(request, field)

    effective_semantic_cache_enabled = update_dict.get(
        "semantic_cache_enabled", doc.semantic_cache_enabled
    )
    effective_semantic_cache_threshold = update_dict.get(
        "semantic_cache_threshold", doc.semantic_cache_threshold
    )
    if effective_semantic_cache_enabled and effective_semantic_cache_threshold is None:
        raise AgentConfigInvalidError(
            "semantic_cache_threshold is required when semantic_cache_enabled is true"
        )

    warnings: list[str] = []
    mismatch_fields = {"chunking_strategy", "embedding_provider", "vector_store"}
    changed_mismatch = {
        f for f in mismatch_fields if f in update_dict and update_dict[f] != getattr(doc, f)
    }
    if changed_mismatch:
        has_docs = await document_dao.find_one({"agent_id": agent_id}) is not None
        if has_docs:
            if "chunking_strategy" in changed_mismatch:
                old_strategy = doc.chunking_strategy
                warnings.append(
                    f"chunking_strategy updated. Existing chunks were generated with "
                    f"'{old_strategy}'. Re-ingestion required for changes to take effect."
                )
            if "embedding_provider" in changed_mismatch:
                old_provider = doc.embedding_provider
                new_provider = str(update_dict["embedding_provider"])
                warnings.append(
                    f"embedding_provider updated from '{old_provider}' to '{new_provider}'. "
                    f"Existing chunks require re-embedding before retrieval quality is reliable."
                )
            if "vector_store" in changed_mismatch:
                old_store = doc.vector_store
                new_store = str(update_dict["vector_store"])
                warnings.append(
                    f"vector_store updated from '{old_store}' to '{new_store}'. "
                    f"Existing vectors remain in '{old_store}'. "
                    f"Re-ingestion required to populate the new store."
                )

    if update_dict:
        update_dict["updated_at"] = datetime.now(UTC)
        await agent_dao.update({"agent_id": agent_id}, update_dict)
        updated_doc = await agent_dao.find_one({"agent_id": agent_id})
        if updated_doc is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found after update")
    else:
        updated_doc = doc

    logger.info(
        "agent_config_updated",
        extra={
            "operation": "update_agent_config",
            "extra_data": {
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "fields_updated": list(update_dict.keys()),
                "warnings": len(warnings),
            },
        },
    )
    return updated_doc, warnings


async def delete_agent(
    agent_id: str,
    tenant_id: str,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    doc = await agent_dao.find_one({"agent_id": agent_id})
    if doc is None:
        raise AgentNotFoundError(f"Agent '{agent_id}' not found")
    if doc.tenant_id != tenant_id:
        raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")

    vs_type = doc.vector_store
    namespace = f"{tenant_id}_{agent_id}"

    all_docs = await document_dao.find({"agent_id": agent_id})

    # Delete vector namespace BEFORE any writes — if this fails, nothing is touched
    vector_store = get_vector_store(vs_type)
    await vector_store.delete_namespace(namespace)

    s3_keys = [d.s3_key for d in all_docs if d.s3_key]
    if s3_keys:
        async with aws_session.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as s3:
            await s3.delete_objects(
                Bucket=settings.s3_document_bucket,
                Delete={"Objects": [{"Key": k} for k in s3_keys]},
            )

    job_ids = [d.job_id for d in all_docs if d.job_id]
    if job_ids:
        await ingestion_job_dao.delete_many({"job_id": {"$in": job_ids}})

    await document_dao.delete_many({"agent_id": agent_id})
    await agent_dao.delete_one({"agent_id": agent_id})

    logger.info(
        "agent_deleted",
        extra={
            "operation": "delete_agent",
            "extra_data": {"agent_id": agent_id, "tenant_id": tenant_id},
        },
    )
