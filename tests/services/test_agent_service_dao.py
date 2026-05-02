from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app.core.config import Settings
from app.core.errors import (
    AgentAlreadyExistsError,
    AgentConfigInvalidError,
    AgentNotFoundError,
    ForbiddenError,
)
from app.models.agent import AgentConfigUpdateRequest, AgentCreateRequest, AgentDocument
from app.models.document import DocumentRecord, DocumentStatus
from app.services import agent_service

TENANT_ID = "test-tenant-id"


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        sqs_ingestion_queue_url="http://localhost/queue",
    )


def _make_agent(**overrides: object) -> AgentDocument:
    base: dict[str, object] = {
        "agent_id": "507f1f77bcf86cd799439011",
        "tenant_id": TENANT_ID,
        "name": "my-rag-agent",
        "chunking_strategy": "fixed_size",
        "vector_store": "pgvector",
        "embedding_provider": "openai",
        "llm_provider": "anthropic",
        "retrieval_mode": "dense",
        "reranker": "none",
        "top_k": 10,
        "semantic_cache_enabled": False,
        "semantic_cache_threshold": None,
        "status": "active",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return AgentDocument(**base)


def _make_document(**overrides: object) -> DocumentRecord:
    base: dict[str, object] = {
        "document_id": str(ObjectId()),
        "agent_id": "507f1f77bcf86cd799439011",
        "tenant_id": TENANT_ID,
        "filename": "doc.pdf",
        "file_type": "pdf",
        "s3_key": "tenant/agent/doc.pdf",
        "job_id": str(ObjectId()),
        "status": DocumentStatus.ready,
        "error_reason": None,
        "created_at": datetime.now(UTC),
    }
    base.update(overrides)
    return DocumentRecord(**base)


VALID_REQUEST = AgentCreateRequest(
    name="my-agent",
    chunking_strategy="fixed_size",
    vector_store="pgvector",
    embedding_provider="openai",
    llm_provider="anthropic",
    retrieval_mode="dense",
    reranker="none",
    top_k=10,
)


@pytest.mark.asyncio
async def test_create_agent_success() -> None:
    with patch.object(agent_service.agent_dao, "find_one", AsyncMock(return_value=None)), patch.object(
        agent_service.agent_dao, "insert_one", AsyncMock()
    ) as insert_mock:
        result = await agent_service.create_agent(VALID_REQUEST, TENANT_ID)

    assert isinstance(result, AgentDocument)
    assert result.tenant_id == TENANT_ID
    insert_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_agent_rejects_mismatched_tenant() -> None:
    with pytest.raises(ForbiddenError):
        await agent_service.create_agent(
            VALID_REQUEST.model_copy(update={"tenant_id": "other-tenant"}),
            TENANT_ID,
        )


@pytest.mark.asyncio
async def test_create_agent_duplicate_name() -> None:
    with patch.object(
        agent_service.agent_dao, "find_one", AsyncMock(return_value=_make_agent(name="my-agent"))
    ):
        with pytest.raises(AgentAlreadyExistsError):
            await agent_service.create_agent(VALID_REQUEST, TENANT_ID)


@pytest.mark.asyncio
async def test_get_agent_checks_tenant_ownership() -> None:
    with patch.object(
        agent_service.agent_dao,
        "find_one",
        AsyncMock(return_value=_make_agent(tenant_id="other-tenant")),
    ):
        with pytest.raises(ForbiddenError):
            await agent_service.get_agent("507f1f77bcf86cd799439011", TENANT_ID)


@pytest.mark.asyncio
async def test_list_agents_returns_cursor_when_has_more() -> None:
    docs = [
        _make_agent(agent_id="507f1f77bcf86cd799439011"),
        _make_agent(agent_id="507f1f77bcf86cd799439012"),
        _make_agent(agent_id="507f1f77bcf86cd799439013"),
    ]
    for idx, doc in enumerate(docs, start=1):
        doc.id = ObjectId(f"507f1f77bcf86cd7994390{10+idx}")

    with patch.object(agent_service.agent_dao, "find", AsyncMock(return_value=docs)):
        items, next_cursor = await agent_service.list_agents(TENANT_ID, limit=2)

    assert len(items) == 2
    assert next_cursor is not None


@pytest.mark.asyncio
async def test_update_agent_config_adds_warning_when_documents_exist() -> None:
    existing = _make_agent(chunking_strategy="fixed_size")
    updated = _make_agent(chunking_strategy="semantic")
    with patch.object(
        agent_service.agent_dao, "find_one", AsyncMock(side_effect=[existing, updated])
    ), patch.object(agent_service.document_dao, "find_one", AsyncMock(return_value=_make_document())), patch.object(
        agent_service.agent_dao, "update", AsyncMock()
    ):
        result, warnings = await agent_service.update_agent_config(
            existing.agent_id,
            TENANT_ID,
            AgentConfigUpdateRequest(chunking_strategy="semantic"),
        )

    assert result.chunking_strategy == "semantic"
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_update_agent_config_sets_embedding_provider_mismatch_flag_on_provider_change() -> None:
    existing = _make_agent(embedding_provider="openai")
    updated = _make_agent(embedding_provider="cohere", embedding_provider_mismatch=True)
    with patch.object(
        agent_service.agent_dao, "find_one", AsyncMock(side_effect=[existing, updated])
    ), patch.object(agent_service.document_dao, "find_one", AsyncMock(return_value=_make_document())), patch.object(
        agent_service.agent_dao, "update", AsyncMock()
    ) as update_mock:
        result, warnings = await agent_service.update_agent_config(
            existing.agent_id,
            TENANT_ID,
            AgentConfigUpdateRequest(embedding_provider="cohere"),
        )

    assert result.embedding_provider == "cohere"
    assert result.embedding_provider_mismatch is True
    assert len(warnings) == 1
    update_payload = update_mock.await_args.args[1]
    assert update_payload["embedding_provider_mismatch"] is True


@pytest.mark.asyncio
async def test_update_agent_config_rejects_missing_threshold() -> None:
    with patch.object(
        agent_service.agent_dao, "find_one", AsyncMock(return_value=_make_agent())
    ):
        with pytest.raises(AgentConfigInvalidError):
            await agent_service.update_agent_config(
                "507f1f77bcf86cd799439011",
                TENANT_ID,
                AgentConfigUpdateRequest(semantic_cache_enabled=True),
            )


@pytest.mark.asyncio
async def test_delete_agent_cleans_up_documents_and_jobs() -> None:
    doc = _make_agent()
    docs = [
        _make_document(job_id="job-1", s3_key="a"),
        _make_document(document_id=str(ObjectId()), job_id="job-2", s3_key="b"),
    ]
    delete_namespace = AsyncMock()
    delete_many_docs = AsyncMock()
    delete_many_jobs = AsyncMock()
    delete_agent_doc = AsyncMock()
    s3_client = AsyncMock()
    s3_client.delete_objects = AsyncMock(return_value={})
    s3_cm = MagicMock()
    s3_cm.__aenter__ = AsyncMock(return_value=s3_client)
    s3_cm.__aexit__ = AsyncMock(return_value=None)
    aws_session = MagicMock()
    aws_session.client = MagicMock(return_value=s3_cm)

    with patch.object(agent_service.agent_dao, "find_one", AsyncMock(return_value=doc)), patch.object(
        agent_service.document_dao, "find", AsyncMock(return_value=docs)
    ), patch.object(agent_service.document_dao, "delete_many", delete_many_docs), patch.object(
        agent_service.ingestion_job_dao, "delete_many", delete_many_jobs
    ), patch.object(agent_service.agent_dao, "delete_one", delete_agent_doc), patch(
        "app.services.agent_service.get_vector_store",
        return_value=MagicMock(delete_namespace=delete_namespace),
    ):
        await agent_service.delete_agent(doc.agent_id, TENANT_ID, aws_session, _make_settings())

    delete_many_docs.assert_awaited_once_with({"agent_id": doc.agent_id})
    delete_many_jobs.assert_awaited_once()
    delete_agent_doc.assert_awaited_once_with({"agent_id": doc.agent_id})


@pytest.mark.asyncio
async def test_delete_agent_not_found() -> None:
    with patch.object(agent_service.agent_dao, "find_one", AsyncMock(return_value=None)):
        with pytest.raises(AgentNotFoundError):
            await agent_service.delete_agent(
                "missing-agent",
                TENANT_ID,
                MagicMock(),
                _make_settings(),
            )
