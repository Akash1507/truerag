import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.dependencies import get_vector_store
from app.core.errors import TenantAlreadyExistsError, TenantNotFoundError
from app.models.tenant import TenantDocument, TenantListItem
from app.utils.observability import get_logger
from app.utils.pagination import decode_cursor, encode_cursor

logger = get_logger(__name__)


async def create_tenant(name: str, db: AsyncIOMotorDatabase[Any]) -> tuple[TenantDocument, str]:
    existing = await db["tenants"].find_one({"name": name})
    if existing:
        raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists")

    raw_key = secrets.token_urlsafe(32)
    api_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    tenant_id = str(ObjectId())
    settings = get_settings()
    now = datetime.now(UTC)

    doc: dict[str, Any] = {
        "tenant_id": tenant_id,
        "name": name,
        "api_key_hash": api_key_hash,
        "rate_limit_rpm": settings.default_rate_limit_rpm,
        "created_at": now,
    }
    try:
        await db["tenants"].insert_one(doc)
    except DuplicateKeyError as exc:
        raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists") from exc

    tenant = TenantDocument(
        tenant_id=tenant_id,
        name=name,
        api_key_hash=api_key_hash,
        rate_limit_rpm=settings.default_rate_limit_rpm,
        created_at=now,
    )
    logger.info(
        "tenant_created",
        extra={"operation": "create_tenant", "extra_data": {"tenant_id": tenant_id}},
    )
    return tenant, raw_key


async def list_tenants(
    db: AsyncIOMotorDatabase[Any],
    cursor: str | None,
    limit: int,
) -> tuple[list[TenantListItem], str | None]:
    query: dict[str, Any] = {}
    if cursor:
        oid = decode_cursor(cursor)
        query["_id"] = {"$gt": oid}

    raw_docs: list[dict[str, Any]] = (
        await db["tenants"].find(query).sort("_id", 1).limit(limit + 1).to_list(None)
    )

    has_more = len(raw_docs) > limit
    if has_more:
        raw_docs = raw_docs[:limit]

    next_cursor: str | None = encode_cursor(raw_docs[-1]["_id"]) if has_more else None
    settings = get_settings()
    items = [
        TenantListItem(
            tenant_id=doc["tenant_id"],
            name=doc["name"],
            rate_limit_rpm=doc.get("rate_limit_rpm") or settings.default_rate_limit_rpm,
            created_at=doc["created_at"],
        )
        for doc in raw_docs
    ]

    logger.debug(
        "list_tenants",
        extra={"operation": "list_tenants", "extra_data": {"count": len(items)}},
    )
    return items, next_cursor


async def delete_tenant(tenant_id: str, db: AsyncIOMotorDatabase[Any]) -> None:
    tenant_doc = await db["tenants"].find_one({"tenant_id": tenant_id})
    if not tenant_doc:
        raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

    agents: list[dict[str, Any]] = await db["agents"].find({"tenant_id": tenant_id}).to_list(None)

    for agent in agents:
        vs_type: str = agent.get("vector_store", "pgvector")
        agent_id: str = agent["agent_id"]
        namespace = f"{tenant_id}_{agent_id}"
        vector_store = get_vector_store(vs_type)
        await vector_store.delete_namespace(namespace)

    await db["agents"].delete_many({"tenant_id": tenant_id})
    await db["tenants"].delete_one({"tenant_id": tenant_id})

    logger.info(
        "tenant_deleted",
        extra={
            "operation": "delete_tenant",
            "extra_data": {"tenant_id": tenant_id, "agents_deleted": len(agents)},
        },
    )
