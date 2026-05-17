from __future__ import annotations

import hashlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings, get_settings
from app.core.dependencies import get_vector_store
from app.core.errors import (
    InvalidCursorError,
    TenantAlreadyExistsError,
    TenantNotFoundError,
    TrueRAGError,
)
from app.db.dao.agent_dao import AgentDAO, agent_dao
from app.db.dao.document_dao import DocumentDAO, document_dao
from app.db.dao.ingestion_job_dao import IngestionJobDAO, ingestion_job_dao
from app.db.dao.tenant_dao import TenantDAO, tenant_dao
from app.models.tenant import (
    AdminTenantItem,
    AdminTenantListResponse,
    MeResponse,
    TenantBudgetResponse,
    TenantCreateResponse,
    TenantDocument,
    TenantListItem,
    TenantListResponse,
    TenantUpdateRequest,
    TenantUpdateResponse,
)
from app.utils.observability import get_logger
from app.utils.pagination import decode_cursor, encode_cursor

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
                        extra={"operation": operation, "extra_data": {"service": "tenant_service"}},
                    )
                    raise

            return wrapper

        return decorator


class TenantService:
    def __init__(
        self,
        tenant_dao_dep: TenantDAO,
        agent_dao_dep: AgentDAO,
        document_dao_dep: DocumentDAO,
        ingestion_job_dao_dep: IngestionJobDAO,
        settings_getter: Callable[[], Settings] = get_settings,
        vector_store_getter: Callable[[str], Any] = get_vector_store,
    ) -> None:
        self._tenant_dao = tenant_dao_dep
        self._agent_dao = agent_dao_dep
        self._document_dao = document_dao_dep
        self._ingestion_job_dao = ingestion_job_dao_dep
        self._settings_getter = settings_getter
        self._vector_store_getter = vector_store_getter

    async def _create_tenant_legacy(self, name: str, display_name: str | None = None) -> tuple[TenantDocument, str]:
        existing = await self._tenant_dao.find_one({"name": name})
        if existing:
            raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists")

        raw_key = secrets.token_urlsafe(32)
        api_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        settings = self._settings_getter()
        tenant = TenantDocument(
            tenant_id=str(ObjectId()),
            name=name,
            display_name=display_name,
            api_key_hash=api_key_hash,
            rate_limit_rpm=settings.default_rate_limit_rpm,
            created_at=datetime.now(UTC),
        )
        try:
            await self._tenant_dao.insert_one(tenant)
        except DuplicateKeyError as exc:
            raise TenantAlreadyExistsError(f"Tenant with name '{name}' already exists") from exc

        logger.info(
            "tenant_created",
            extra={"operation": "create_tenant", "extra_data": {"tenant_id": tenant.tenant_id}},
        )
        return tenant, raw_key

    async def _list_tenants_legacy(
        self,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[TenantListItem], str | None]:
        query: dict[str, object] = {}
        if cursor:
            oid = decode_cursor(cursor)
            query["_id"] = {"$gt": oid}

        docs = await self._tenant_dao.find(query, sort=[("_id", 1)], limit=limit + 1)

        has_more = len(docs) > limit
        if has_more:
            docs = docs[:limit]

        next_cursor: str | None = (
            encode_cursor(docs[-1].id) if has_more and docs and docs[-1].id else None
        )
        settings = self._settings_getter()
        items = [
            TenantListItem(
                tenant_id=doc.tenant_id,
                name=doc.name,
                display_name=doc.display_name,
                rate_limit_rpm=(
                    rpm
                    if (rpm := doc.rate_limit_rpm) is not None
                    else settings.default_rate_limit_rpm
                ),
                created_at=doc.created_at,
            )
            for doc in docs
        ]
        return items, next_cursor

    @service_method("create_tenant")
    async def register(self, name: str, display_name: str | None = None) -> TenantCreateResponse:
        tenant, raw_key = await self._create_tenant_legacy(name, display_name)
        settings = self._settings_getter()
        return TenantCreateResponse(
            tenant_id=tenant.tenant_id,
            name=tenant.name,
            display_name=tenant.display_name,
            api_key=raw_key,
            rate_limit_rpm=(
                tenant.rate_limit_rpm
                if tenant.rate_limit_rpm is not None
                else settings.default_rate_limit_rpm
            ),
            created_at=tenant.created_at,
        )

    @service_method("list_tenants")
    async def list(self, cursor: str | None, limit: int) -> TenantListResponse:
        items, next_cursor = await self._list_tenants_legacy(cursor, limit)
        logger.debug(
            "list_tenants",
            extra={"operation": "list_tenants", "extra_data": {"count": len(items)}},
        )
        return TenantListResponse(items=items, next_cursor=next_cursor)

    @service_method("delete_tenant")
    async def delete_tenant(self, tenant_id: str) -> None:
        tenant_doc = await self._tenant_dao.find_one({"tenant_id": tenant_id})
        if not tenant_doc:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

        agents = await self._agent_dao.find({"tenant_id": tenant_id})

        await self._agent_dao.delete_many({"tenant_id": tenant_id})
        await self._document_dao.delete_many({"tenant_id": tenant_id})
        await self._ingestion_job_dao.delete_many({"tenant_id": tenant_id})
        await self._tenant_dao.delete_one({"tenant_id": tenant_id})

        for agent in agents:
            vs_type = agent.vector_store
            agent_id = agent.agent_id
            namespace = f"{tenant_id}_{agent_id}"
            vector_store = get_vector_store(vs_type)
            try:
                await vector_store.delete_namespace(namespace)
            except Exception as exc:
                logger.warning(
                    "vector_namespace_delete_failed",
                    extra={
                        "operation": "delete_tenant",
                        "extra_data": {"namespace": namespace, "error": str(exc)},
                    },
                )

        logger.info(
            "tenant_deleted",
            extra={
                "operation": "delete_tenant",
                "extra_data": {"tenant_id": tenant_id, "agents_deleted": len(agents)},
            },
        )

    @service_method("update_tenant")
    async def update_tenant(self, tenant_id: str, update: TenantUpdateRequest) -> TenantUpdateResponse:
        tenant_doc = await self._tenant_dao.find_one({"tenant_id": tenant_id})
        if not tenant_doc:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

        update_dict = update.model_dump(exclude_unset=True)
        if update_dict:
            await self._tenant_dao.update({"tenant_id": tenant_id}, update_dict)

        updated = await self._tenant_dao.find_one({"tenant_id": tenant_id})
        if updated is None:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' not found after update")

        logger.info(
            "tenant_updated",
            extra={"operation": "update_tenant", "extra_data": {"tenant_id": tenant_id, "fields": list(update_dict)}},
        )
        return TenantUpdateResponse(
            tenant_id=updated.tenant_id,
            name=updated.name,
            display_name=updated.display_name,
            role=updated.role,
            monthly_token_budget=updated.monthly_token_budget,
            created_at=updated.created_at,
        )

    @service_method("update_tenant_budget")
    async def update_budget(self, tenant_id: str, monthly_token_budget: int | None) -> TenantBudgetResponse:
        tenant_doc = await self._tenant_dao.find_one({"tenant_id": tenant_id})
        if not tenant_doc:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

        await self._tenant_dao.update(
            {"tenant_id": tenant_id},
            {"monthly_token_budget": monthly_token_budget},
        )
        updated = await self._tenant_dao.find_one({"tenant_id": tenant_id})
        if updated is None:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' not found after update")

        logger.info(
            "tenant_budget_updated",
            extra={
                "operation": "update_tenant_budget",
                "extra_data": {
                    "tenant_id": tenant_id,
                    "monthly_token_budget": monthly_token_budget,
                },
            },
        )
        return TenantBudgetResponse(
            tenant_id=updated.tenant_id,
            name=updated.name,
            display_name=updated.display_name,
            rate_limit_rpm=updated.rate_limit_rpm,
            role=updated.role,
            monthly_token_budget=updated.monthly_token_budget,
            created_at=updated.created_at,
        )

    @service_method("get_me")
    async def get_me(self, tenant: TenantDocument) -> MeResponse:
        return MeResponse(
            tenant_id=tenant.tenant_id,
            name=tenant.name,
            display_name=tenant.display_name,
            role=tenant.role,
        )

    @service_method("admin_list_tenants")
    async def admin_list_tenants(self) -> AdminTenantListResponse:
        tenants = await self._tenant_dao.find({}, sort=[("created_at", 1)], limit=1000)
        items: list[AdminTenantItem] = []
        for tenant in tenants:
            agents = await self._agent_dao.find({"tenant_id": tenant.tenant_id})
            items.append(
                AdminTenantItem(
                    tenant_id=tenant.tenant_id,
                    name=tenant.name,
                    display_name=tenant.display_name,
                    role=tenant.role,
                    monthly_token_budget=tenant.monthly_token_budget,
                    created_at=tenant.created_at,
                    agent_count=len(agents),
                )
            )
        return AdminTenantListResponse(items=items, total=len(items))

    async def bootstrap_admin(self, name: str, display_name: str, raw_key: str) -> None:
        """Upsert the admin tenant using a pre-configured API key.

        Called once on startup when ADMIN_API_KEY is set. Idempotent: if the tenant
        already exists it just updates the hash so the key stays in sync with config.
        """
        api_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        existing = await self._tenant_dao.find_one({"name": name})
        if existing:
            await self._tenant_dao.update(
                {"name": name},
                {"api_key_hash": api_key_hash, "role": "admin", "display_name": display_name},
            )
            logger.info("admin_tenant_refreshed", extra={"operation": "bootstrap_admin"})
            return

        settings = self._settings_getter()
        tenant = TenantDocument(
            tenant_id=str(ObjectId()),
            name=name,
            display_name=display_name,
            api_key_hash=api_key_hash,
            role="admin",
            rate_limit_rpm=settings.default_rate_limit_rpm,
            created_at=datetime.now(UTC),
        )
        await self._tenant_dao.insert_one(tenant)
        logger.info(
            "admin_tenant_created",
            extra={"operation": "bootstrap_admin", "extra_data": {"tenant_id": tenant.tenant_id}},
        )

    # Legacy method names preserved for compatibility.
    async def create_tenant(self, name: str, display_name: str | None = None) -> tuple[TenantDocument, str]:
        return await self._create_tenant_legacy(name, display_name)

    async def list_tenants(self, cursor: str | None, limit: int) -> tuple[list[TenantListItem], str | None]:
        return await self._list_tenants_legacy(cursor, limit)


tenant_service = TenantService(
    tenant_dao_dep=tenant_dao,
    agent_dao_dep=agent_dao,
    document_dao_dep=document_dao,
    ingestion_job_dao_dep=ingestion_job_dao,
)


# Legacy compatibility wrappers for non-story call sites.
async def create_tenant(name: str, display_name: str | None = None) -> tuple[TenantDocument, str]:
    return await tenant_service._create_tenant_legacy(name, display_name)


async def list_tenants(
    cursor: str | None,
    limit: int,
) -> tuple[list[TenantListItem], str | None]:
    return await tenant_service._list_tenants_legacy(cursor, limit)


async def delete_tenant(tenant_id: str) -> None:
    await tenant_service.delete_tenant(tenant_id)
