from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

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
