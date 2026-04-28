from datetime import UTC, datetime
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.dependencies import get_vector_store
from app.core.errors import (
    AgentAlreadyExistsError,
    AgentConfigInvalidError,
    AgentNotFoundError,
    ForbiddenError,
)
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
    db: AsyncIOMotorDatabase[Any],
) -> AgentDocument:
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

    existing = await db["agents"].find_one({"tenant_id": tenant_id, "name": request.name})
    if existing is not None:
        raise AgentAlreadyExistsError(
            f"Agent with name '{request.name}' already exists for this tenant"
        )

    agent_id = str(ObjectId())
    now = datetime.now(UTC)

    doc: dict[str, Any] = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "name": request.name,
        "chunking_strategy": request.chunking_strategy,
        "vector_store": request.vector_store,
        "embedding_provider": request.embedding_provider,
        "llm_provider": request.llm_provider,
        "retrieval_mode": request.retrieval_mode,
        "reranker": request.reranker,
        "top_k": request.top_k,
        "semantic_cache_enabled": request.semantic_cache_enabled,
        "semantic_cache_threshold": request.semantic_cache_threshold,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db["agents"].insert_one(doc)
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

    return AgentDocument(**{k: doc[k] for k in AgentDocument.model_fields})


async def get_agent(
    agent_id: str,
    tenant_id: str,
    db: AsyncIOMotorDatabase[Any],
) -> AgentDocument:
    doc = await db["agents"].find_one({"agent_id": agent_id})
    if doc is None:
        raise AgentNotFoundError(f"Agent '{agent_id}' not found")
    if doc["tenant_id"] != tenant_id:
        raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")
    return AgentDocument(**{k: doc[k] for k in AgentDocument.model_fields})


async def list_agents(
    tenant_id: str,
    db: AsyncIOMotorDatabase[Any],
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[AgentDocument], str | None]:
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if cursor:
        oid = decode_cursor(cursor)  # raises ValueError on invalid cursor — caught at route layer
        query["_id"] = {"$gt": oid}

    raw_docs: list[dict[str, Any]] = (
        await db["agents"].find(query).sort("_id", 1).limit(limit + 1).to_list(None)
    )

    has_more = len(raw_docs) > limit
    if has_more:
        raw_docs = raw_docs[:limit]

    next_cursor: str | None = encode_cursor(raw_docs[-1]["_id"]) if has_more else None
    items = [
        AgentDocument(**{k: doc[k] for k in AgentDocument.model_fields})
        for doc in raw_docs
    ]

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
    db: AsyncIOMotorDatabase[Any],
) -> tuple[AgentDocument, list[str]]:
    doc = await db["agents"].find_one({"agent_id": agent_id})
    if doc is None:
        raise AgentNotFoundError(f"Agent '{agent_id}' not found")
    if doc["tenant_id"] != tenant_id:
        raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")

    for field, valid_set in _FIELD_VALIDATORS:
        value: str | None = getattr(request, field)
        if value is not None and value not in valid_set:
            raise AgentConfigInvalidError(
                f"Invalid {field}: {value!r}. Supported values: {sorted(valid_set)}"
            )

    provided_fields = request.model_fields_set
    update_dict: dict[str, Any] = {}
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
    ):
        if field in provided_fields:
            update_dict[field] = getattr(request, field)

    effective_semantic_cache_enabled = update_dict.get(
        "semantic_cache_enabled", doc["semantic_cache_enabled"]
    )
    effective_semantic_cache_threshold = update_dict.get(
        "semantic_cache_threshold", doc["semantic_cache_threshold"]
    )
    if effective_semantic_cache_enabled and effective_semantic_cache_threshold is None:
        raise AgentConfigInvalidError(
            "semantic_cache_threshold is required when semantic_cache_enabled is true"
        )

    warnings: list[str] = []
    mismatch_fields = {"chunking_strategy", "embedding_provider", "vector_store"}
    changed_mismatch = {f for f in mismatch_fields if f in update_dict and update_dict[f] != doc[f]}
    if changed_mismatch:
        has_docs = await db["documents"].find_one({"agent_id": agent_id}) is not None
        if has_docs:
            if "chunking_strategy" in changed_mismatch:
                old_strategy: str = doc["chunking_strategy"]
                warnings.append(
                    f"chunking_strategy updated. Existing chunks were generated with "
                    f"'{old_strategy}'. Re-ingestion required for changes to take effect."
                )
            if "embedding_provider" in changed_mismatch:
                old_provider: str = doc["embedding_provider"]
                new_provider: str = update_dict["embedding_provider"]
                warnings.append(
                    f"embedding_provider updated from '{old_provider}' to '{new_provider}'. "
                    f"Existing chunks require re-embedding before retrieval quality is reliable."
                )
            if "vector_store" in changed_mismatch:
                old_store: str = doc["vector_store"]
                new_store: str = update_dict["vector_store"]
                warnings.append(
                    f"vector_store updated from '{old_store}' to '{new_store}'. "
                    f"Existing vectors remain in '{old_store}'. "
                    f"Re-ingestion required to populate the new store."
                )

    if update_dict:
        update_dict["updated_at"] = datetime.now(UTC)
        await db["agents"].update_one({"agent_id": agent_id}, {"$set": update_dict})
        updated_doc = await db["agents"].find_one({"agent_id": agent_id})
        assert updated_doc is not None
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
    return AgentDocument(**{k: updated_doc[k] for k in AgentDocument.model_fields}), warnings


async def delete_agent(
    agent_id: str,
    tenant_id: str,
    db: AsyncIOMotorDatabase[Any],
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    doc = await db["agents"].find_one({"agent_id": agent_id})
    if doc is None:
        raise AgentNotFoundError(f"Agent '{agent_id}' not found")
    if doc["tenant_id"] != tenant_id:
        raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")

    vs_type: str = doc.get("vector_store", "pgvector")
    namespace = f"{tenant_id}_{agent_id}"

    all_docs: list[dict[str, Any]] = await db["documents"].find(
        {"agent_id": agent_id}
    ).to_list(None)

    # Delete vector namespace BEFORE any writes — if this fails, nothing is touched
    vector_store = get_vector_store(vs_type)
    await vector_store.delete_namespace(namespace)

    s3_keys = [d["s3_key"] for d in all_docs if d.get("s3_key")]
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

    job_ids = [d["job_id"] for d in all_docs if d.get("job_id")]
    if job_ids:
        async with aws_session.client(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ) as dynamo:
            for jid in job_ids:
                await dynamo.delete_item(
                    TableName=settings.dynamodb_jobs_table,
                    Key={"job_id": {"S": jid}},
                )

    await db["documents"].delete_many({"agent_id": agent_id})
    await db["agents"].delete_one({"agent_id": agent_id})

    logger.info(
        "agent_deleted",
        extra={
            "operation": "delete_agent",
            "extra_data": {"agent_id": agent_id, "tenant_id": tenant_id},
        },
    )
