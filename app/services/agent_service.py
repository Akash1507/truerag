from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import aioboto3
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.dependencies import get_vector_store
from app.core.errors import (
    AgentAlreadyExistsError,
    AgentConfigInvalidError,
    AgentNotFoundError,
    ForbiddenError,
    InvalidCursorError,
    SessionNotFoundError,
    TrueRAGError,
)
from app.db.dao.agent_dao import AgentDAO, agent_dao
from app.db.dao.conversation_dao import ConversationSessionDAO, conversation_dao
from app.db.dao.document_dao import DocumentDAO, document_dao
from app.db.dao.ingestion_job_dao import IngestionJobDAO, ingestion_job_dao
from app.models.agent import (
    VALID_CHUNKING_STRATEGIES,
    VALID_EMBEDDING_PROVIDERS,
    VALID_LLM_PROVIDERS,
    VALID_RERANKERS,
    VALID_RETRIEVAL_MODES,
    VALID_VECTOR_STORES,
    AgentConfigUpdateRequest,
    AgentCreateRequest,
    AgentCreateResponse,
    AgentDocument,
    AgentListResponse,
    AgentUpdateResponse,
)
from app.models.conversation import SessionDetailResponse, SessionListResponse, SessionSummary
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
                        extra={"operation": operation, "extra_data": {"service": "agent_service"}},
                    )
                    raise

            return wrapper

        return decorator


_FIELD_VALIDATORS: list[tuple[str, frozenset[str]]] = [
    ("chunking_strategy", VALID_CHUNKING_STRATEGIES),
    ("vector_store", VALID_VECTOR_STORES),
    ("embedding_provider", VALID_EMBEDDING_PROVIDERS),
    ("llm_provider", VALID_LLM_PROVIDERS),
    ("retrieval_mode", VALID_RETRIEVAL_MODES),
    ("reranker", VALID_RERANKERS),
]


def _to_create_response(agent: AgentDocument) -> AgentCreateResponse:
    return AgentCreateResponse(**agent.model_dump())


def _to_update_response(agent: AgentDocument, warnings: list[str]) -> AgentUpdateResponse:
    return AgentUpdateResponse(**agent.model_dump(), warnings=warnings)


class AgentService:
    def __init__(
        self,
        dao: AgentDAO,
        document_dao_dep: DocumentDAO,
        ingestion_job_dao_dep: IngestionJobDAO,
        conversation_dao_dep: ConversationSessionDAO,
        vector_store_getter: Callable[[str], Any] = get_vector_store,
    ) -> None:
        self._dao = dao
        self._document_dao = document_dao_dep
        self._ingestion_job_dao = ingestion_job_dao_dep
        self._conversation_dao = conversation_dao_dep
        self._vector_store_getter = vector_store_getter

    async def _get_agent_document(self, agent_id: str, tenant_id: str) -> AgentDocument:
        doc = await self._dao.find_one({"agent_id": agent_id})
        if doc is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")
        if doc.tenant_id != tenant_id:
            raise ForbiddenError(f"Agent '{agent_id}' does not belong to this tenant")
        return doc

    async def _list_agents_legacy(
        self,
        tenant_id: str,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[AgentDocument], str | None]:
        query: dict[str, object] = {"tenant_id": tenant_id}
        if cursor:
            oid = decode_cursor(cursor)
            query["_id"] = {"$gt": oid}

        docs = await self._dao.find(query, sort=[("_id", 1)], limit=limit + 1)

        has_more = len(docs) > limit
        if has_more:
            docs = docs[:limit]

        next_cursor: str | None = (
            encode_cursor(docs[-1].id) if has_more and docs and docs[-1].id else None
        )
        return docs, next_cursor

    async def _update_agent_config_legacy(
        self,
        agent_id: str,
        tenant_id: str,
        request: AgentConfigUpdateRequest,
    ) -> tuple[AgentDocument, list[str]]:
        doc = await self._get_agent_document(agent_id, tenant_id)

        for field, valid_set in _FIELD_VALIDATORS:
            value: str | None = getattr(request, field)
            if value is not None and value not in valid_set:
                raise AgentConfigInvalidError(
                    f"Invalid {field}: {value!r}. Supported values: {sorted(valid_set)}"
                )

        provided_fields = request.model_fields_set
        update_dict: dict[str, object] = {}
        for field in (
            "display_name",
            "chunking_strategy",
            "chunk_size",
            "chunk_overlap",
            "vector_store",
            "embedding_provider",
            "llm_provider",
            "retrieval_mode",
            "reranker",
            "query_rewrite",
            "hallucination_check_enabled",
            "hyde_enabled",
            "multi_query_enabled",
            "multi_query_count",
            "mmr_enabled",
            "mmr_lambda",
            "context_window_tokens",
            "rerank_pool_size",
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

        effective_chunk_size = int(update_dict.get("chunk_size", doc.chunk_size))
        effective_chunk_overlap = int(update_dict.get("chunk_overlap", doc.chunk_overlap))
        if effective_chunk_overlap > effective_chunk_size // 2:
            raise AgentConfigInvalidError("chunk_overlap must be <= chunk_size // 2")

        warnings: list[str] = []
        mismatch_fields = {"chunking_strategy", "embedding_provider", "vector_store"}
        changed_mismatch = {
            f for f in mismatch_fields if f in update_dict and update_dict[f] != getattr(doc, f)
        }
        if changed_mismatch:
            has_docs = await self._document_dao.find_one({"agent_id": agent_id}) is not None
            if has_docs:
                if "chunking_strategy" in changed_mismatch:
                    old_strategy = doc.chunking_strategy
                    warnings.append(
                        "chunking_strategy updated. Existing chunks were generated with "
                        f"'{old_strategy}'. Re-ingestion required for changes to take effect."
                    )
                if "embedding_provider" in changed_mismatch:
                    old_provider = doc.embedding_provider
                    new_provider = str(update_dict["embedding_provider"])
                    warnings.append(
                        f"embedding_provider updated from '{old_provider}' to '{new_provider}'. "
                        "Existing chunks require re-embedding before retrieval quality is reliable."
                    )
                    update_dict["embedding_provider_mismatch"] = True
                if "vector_store" in changed_mismatch:
                    old_store = doc.vector_store
                    new_store = str(update_dict["vector_store"])
                    warnings.append(
                        f"vector_store updated from '{old_store}' to '{new_store}'. "
                        f"Existing vectors remain in '{old_store}'. "
                        "Re-ingestion required to populate the new store."
                    )

        if update_dict:
            update_dict["updated_at"] = datetime.now(UTC)
            await self._dao.update({"agent_id": agent_id}, update_dict)
            updated_doc = await self._dao.find_one({"agent_id": agent_id})
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

    @service_method("create_agent")
    async def create(self, request: AgentCreateRequest, tenant_id: str) -> AgentCreateResponse:
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
        if request.chunk_overlap > request.chunk_size // 2:
            raise AgentConfigInvalidError("chunk_overlap must be <= chunk_size // 2")

        existing = await self._dao.find_one({"tenant_id": tenant_id, "name": request.name})
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
            display_name=request.display_name,
            chunking_strategy=request.chunking_strategy,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            vector_store=request.vector_store,
            embedding_provider=request.embedding_provider,
            llm_provider=request.llm_provider,
            retrieval_mode=request.retrieval_mode,
            reranker=request.reranker,
            query_rewrite=request.query_rewrite,
            hyde_enabled=request.hyde_enabled,
            multi_query_enabled=request.multi_query_enabled,
            multi_query_count=request.multi_query_count,
            mmr_enabled=request.mmr_enabled,
            mmr_lambda=request.mmr_lambda,
            context_window_tokens=request.context_window_tokens,
            rerank_pool_size=request.rerank_pool_size,
            top_k=request.top_k,
            semantic_cache_enabled=request.semantic_cache_enabled,
            semantic_cache_threshold=request.semantic_cache_threshold,
            faithfulness_threshold=request.faithfulness_threshold,
            status="active",
            created_at=now,
            updated_at=now,
        )
        try:
            await self._dao.insert_one(agent)
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
        return _to_create_response(agent)

    @service_method("get_agent")
    async def get(self, agent_id: str, tenant_id: str) -> AgentCreateResponse:
        doc = await self._get_agent_document(agent_id, tenant_id)
        return _to_create_response(doc)

    @service_method("list_agents")
    async def list(
        self,
        tenant_id: str,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> AgentListResponse:
        items, next_cursor = await self._list_agents_legacy(tenant_id, cursor, limit)
        response_items = [_to_create_response(item) for item in items]
        logger.debug(
            "list_agents",
            extra={
                "operation": "list_agents",
                "extra_data": {"count": len(response_items), "tenant_id": tenant_id},
            },
        )
        return AgentListResponse(items=response_items, next_cursor=next_cursor)

    @service_method("update_agent_config")
    async def update_config(
        self,
        agent_id: str,
        tenant_id: str,
        request: AgentConfigUpdateRequest,
    ) -> AgentUpdateResponse:
        updated_doc, warnings = await self._update_agent_config_legacy(agent_id, tenant_id, request)
        return _to_update_response(updated_doc, warnings)

    @service_method("delete_agent")
    async def delete(
        self,
        agent_id: str,
        tenant_id: str,
        aws_session: aioboto3.Session,
        settings: Settings,
    ) -> None:
        doc = await self._get_agent_document(agent_id, tenant_id)
        vs_type = doc.vector_store
        namespace = f"{tenant_id}_{agent_id}"

        all_docs = await self._document_dao.find({"agent_id": agent_id})

        vector_store = self._vector_store_getter(vs_type)
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
            await self._ingestion_job_dao.delete_many({"job_id": {"$in": job_ids}})

        await self._document_dao.delete_many({"agent_id": agent_id})
        await self._dao.delete_one({"agent_id": agent_id})

        logger.info(
            "agent_deleted",
            extra={
                "operation": "delete_agent",
                "extra_data": {"agent_id": agent_id, "tenant_id": tenant_id},
            },
        )

    @service_method("list_sessions")
    async def list_sessions(self, agent_id: str, tenant_id: str) -> SessionListResponse:
        await self._get_agent_document(agent_id, tenant_id)
        sessions = await self._conversation_dao.list_sessions(agent_id, tenant_id)
        summaries = [
            SessionSummary(
                session_id=s.session_id,
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=len(s.messages),
                preview=next(
                    (m.content[:80] for m in s.messages if m.role == "user"), None
                ),
            )
            for s in sessions
        ]
        return SessionListResponse(sessions=summaries)

    @service_method("get_session")
    async def get_session(
        self, agent_id: str, session_id: str, tenant_id: str
    ) -> SessionDetailResponse:
        await self._get_agent_document(agent_id, tenant_id)
        session = await self._conversation_dao.get_session(session_id, agent_id, tenant_id)
        if session is None:
            raise SessionNotFoundError(f"Session '{session_id}' not found")
        return SessionDetailResponse(
            session_id=session.session_id,
            messages=session.messages,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    # Legacy method names preserved for compatibility.
    async def create_agent(self, request: AgentCreateRequest, tenant_id: str) -> AgentCreateResponse:
        return await self.create(request, tenant_id)

    async def get_agent(self, agent_id: str, tenant_id: str) -> AgentDocument:
        return await self._get_agent_document(agent_id, tenant_id)

    async def list_agents(
        self,
        tenant_id: str,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[AgentDocument], str | None]:
        return await self._list_agents_legacy(tenant_id, cursor, limit)

    async def update_agent_config(
        self,
        agent_id: str,
        tenant_id: str,
        request: AgentConfigUpdateRequest,
    ) -> tuple[AgentDocument, list[str]]:
        return await self._update_agent_config_legacy(agent_id, tenant_id, request)

    async def delete_agent(
        self,
        agent_id: str,
        tenant_id: str,
        aws_session: aioboto3.Session,
        settings: Settings,
    ) -> None:
        await self.delete(agent_id, tenant_id, aws_session, settings)


agent_service = AgentService(
    dao=agent_dao,
    document_dao_dep=document_dao,
    ingestion_job_dao_dep=ingestion_job_dao,
    conversation_dao_dep=conversation_dao,
)


# Legacy compatibility wrappers for non-story call sites.
async def create_agent(request: AgentCreateRequest, tenant_id: str) -> AgentCreateResponse:
    return await agent_service.create(request, tenant_id)


async def get_agent(agent_id: str, tenant_id: str) -> AgentDocument:
    return await agent_service._get_agent_document(agent_id, tenant_id)


async def list_agents(
    tenant_id: str,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[AgentDocument], str | None]:
    return await agent_service._list_agents_legacy(tenant_id, cursor, limit)


async def update_agent_config(
    agent_id: str,
    tenant_id: str,
    request: AgentConfigUpdateRequest,
) -> tuple[AgentDocument, list[str]]:
    return await agent_service._update_agent_config_legacy(agent_id, tenant_id, request)


async def delete_agent(
    agent_id: str,
    tenant_id: str,
    aws_session: aioboto3.Session,
    settings: Settings,
) -> None:
    await agent_service.delete(agent_id, tenant_id, aws_session, settings)
