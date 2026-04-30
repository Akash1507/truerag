import hashlib
import secrets
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.dependencies import get_vector_store
from app.core.errors import TenantAlreadyExistsError, TenantNotFoundError
from app.db.dao.agent_dao import agent_dao
from app.db.dao.tenant_dao import tenant_dao
from app.models.tenant import TenantDocument, TenantListItem
from app.utils.observability import get_logger
from app.utils.pagination import decode_cursor, encode_cursor

logger = get_logger(__name__)


async def create_tenant(name: str) -> tuple[TenantDocument, str]:
    existing = await tenant_dao.find_one({"name": name})
    if existing:
        raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists")

    raw_key = secrets.token_urlsafe(32)
    api_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    settings = get_settings()
    tenant = TenantDocument(
        tenant_id=str(ObjectId()),
        name=name,
        api_key_hash=api_key_hash,
        rate_limit_rpm=settings.default_rate_limit_rpm,
        created_at=datetime.now(UTC),
    )
    try:
        await tenant_dao.insert_one(tenant)
    except DuplicateKeyError as exc:
        raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists") from exc

    logger.info(
        "tenant_created",
        extra={"operation": "create_tenant", "extra_data": {"tenant_id": tenant.tenant_id}},
    )
    return tenant, raw_key


async def list_tenants(
    cursor: str | None,
    limit: int,
) -> tuple[list[TenantListItem], str | None]:
    query: dict[str, object] = {}
    if cursor:
        oid = decode_cursor(cursor)
        query["_id"] = {"$gt": oid}

    docs = await tenant_dao.find(query, sort=[("_id", 1)], limit=limit + 1)

    has_more = len(docs) > limit
    if has_more:
        docs = docs[:limit]

    next_cursor: str | None = encode_cursor(docs[-1].id) if has_more and docs[-1].id else None
    settings = get_settings()
    items = [
        TenantListItem(
            tenant_id=doc.tenant_id,
            name=doc.name,
            rate_limit_rpm=(
                rpm
                if (rpm := doc.rate_limit_rpm) is not None
                else settings.default_rate_limit_rpm
            ),
            created_at=doc.created_at,
        )
        for doc in docs
    ]

    logger.debug(
        "list_tenants",
        extra={"operation": "list_tenants", "extra_data": {"count": len(items)}},
    )
    return items, next_cursor


async def delete_tenant(tenant_id: str) -> None:
    tenant_doc = await tenant_dao.find_one({"tenant_id": tenant_id})
    if not tenant_doc:
        raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

    agents = await agent_dao.find({"tenant_id": tenant_id})

    await agent_dao.delete_many({"tenant_id": tenant_id})
    await tenant_dao.delete_one({"tenant_id": tenant_id})

    for agent in agents:
        vs_type = agent.vector_store
        agent_id = agent.agent_id
        namespace = f"{tenant_id}_{agent_id}"
        vector_store = get_vector_store(vs_type)
        await vector_store.delete_namespace(namespace)

    logger.info(
        "tenant_deleted",
        extra={
            "operation": "delete_tenant",
            "extra_data": {"tenant_id": tenant_id, "agents_deleted": len(agents)},
        },
    )
