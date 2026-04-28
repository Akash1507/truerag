from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.errors import (
    AgentAlreadyExistsError,
    AgentConfigInvalidError,
    AgentNotFoundError,
    ForbiddenError,
)
from app.models.agent import AgentConfigUpdateRequest, AgentCreateRequest, AgentDocument
from app.services.agent_service import (
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
    update_agent_config,
)

TENANT_ID = "test-tenant-id"


def _make_aws_mock() -> MagicMock:
    def make_cm(mock_client: AsyncMock) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_s3 = AsyncMock()
    mock_s3.delete_objects = AsyncMock(return_value={})

    mock_dynamo = AsyncMock()
    mock_dynamo.delete_item = AsyncMock(return_value={})

    def client_factory(service: str, **kwargs: Any) -> MagicMock:
        if service == "s3":
            return make_cm(mock_s3)
        return make_cm(mock_dynamo)

    mock_session = MagicMock()
    mock_session.client = MagicMock(side_effect=client_factory)
    return mock_session


def _make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        aws_endpoint_url=None,
        s3_document_bucket="test-bucket",
        dynamodb_jobs_table="test-jobs",
        sqs_ingestion_queue_url="http://localhost/queue",
    )

FAKE_AGENT_DOC: dict = {
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
    "_id": ObjectId("507f1f77bcf86cd799439011"),
}

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


def make_mock_db(
    find_one_return: dict | None = None,
    insert_raises: Exception | None = None,
    find_return_list: list[dict] | None = None,
    agents_find_one_side_effect: list[dict | None] | None = None,
    update_one_return: MagicMock | None = None,
    documents_find_one_return: dict | None = None,
    documents_find_return_list: list[dict] | None = None,
) -> MagicMock:
    mock_agents = MagicMock()
    if agents_find_one_side_effect is not None:
        mock_agents.find_one = AsyncMock(side_effect=agents_find_one_side_effect)
    else:
        mock_agents.find_one = AsyncMock(return_value=find_one_return)
    if insert_raises is not None:
        mock_agents.insert_one = AsyncMock(side_effect=insert_raises)
    else:
        mock_agents.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake-oid"))
    mock_agents.update_one = AsyncMock(return_value=update_one_return or MagicMock())

    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=find_return_list or [])
    mock_agents.find = MagicMock(return_value=mock_cursor)

    mock_agents.delete_one = AsyncMock(return_value=MagicMock())
    mock_agents.delete_many = AsyncMock(return_value=MagicMock())

    mock_documents = MagicMock()
    mock_documents.find_one = AsyncMock(return_value=documents_find_one_return)
    mock_documents.delete_one = AsyncMock(return_value=MagicMock())
    mock_documents.delete_many = AsyncMock(return_value=MagicMock())
    mock_doc_cursor = MagicMock()
    mock_doc_cursor.to_list = AsyncMock(return_value=documents_find_return_list or [])
    mock_documents.find = MagicMock(return_value=mock_doc_cursor)

    def get_collection(name: str) -> MagicMock:
        if name == "agents":
            return mock_agents
        elif name == "documents":
            return mock_documents
        return MagicMock()

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=get_collection)
    return mock_db


@pytest.mark.asyncio
async def test_create_agent_success() -> None:
    db = make_mock_db(find_one_return=None)
    result = await create_agent(VALID_REQUEST, TENANT_ID, db)

    assert isinstance(result, AgentDocument)
    assert result.tenant_id == TENANT_ID
    assert result.name == "my-agent"
    assert result.status == "active"
    assert result.chunking_strategy == "fixed_size"
    assert result.vector_store == "pgvector"
    assert result.embedding_provider == "openai"
    assert result.llm_provider == "anthropic"
    assert result.retrieval_mode == "dense"
    assert result.reranker == "none"
    assert result.top_k == 10
    assert result.agent_id


@pytest.mark.asyncio
async def test_create_agent_invalid_chunking_strategy() -> None:
    db = make_mock_db()
    request = AgentCreateRequest(
        name="my-agent",
        chunking_strategy="bad_strategy",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=10,
    )
    with pytest.raises(AgentConfigInvalidError) as exc_info:
        await create_agent(request, TENANT_ID, db)

    assert "chunking_strategy" in str(exc_info.value)
    assert "Supported values" in str(exc_info.value)
    db["agents"].insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_create_agent_invalid_vector_store() -> None:
    db = make_mock_db()
    request = AgentCreateRequest(
        name="my-agent",
        chunking_strategy="fixed_size",
        vector_store="redis",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=10,
    )
    with pytest.raises(AgentConfigInvalidError):
        await create_agent(request, TENANT_ID, db)


@pytest.mark.asyncio
async def test_create_agent_invalid_llm_provider() -> None:
    db = make_mock_db()
    request = AgentCreateRequest(
        name="my-agent",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="mistral",
        retrieval_mode="dense",
        reranker="none",
        top_k=10,
    )
    with pytest.raises(AgentConfigInvalidError):
        await create_agent(request, TENANT_ID, db)


@pytest.mark.asyncio
async def test_create_agent_duplicate_name() -> None:
    existing = {"agent_id": "existing", "tenant_id": TENANT_ID, "name": "my-agent"}
    db = make_mock_db(find_one_return=existing)
    with pytest.raises(AgentAlreadyExistsError):
        await create_agent(VALID_REQUEST, TENANT_ID, db)

    db["agents"].insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_create_agent_duplicate_key_from_db() -> None:
    db = make_mock_db(find_one_return=None, insert_raises=DuplicateKeyError("duplicate"))
    with pytest.raises(AgentAlreadyExistsError):
        await create_agent(VALID_REQUEST, TENANT_ID, db)


@pytest.mark.asyncio
async def test_create_agent_config_error_message_format() -> None:
    db = make_mock_db()
    request = AgentCreateRequest(
        name="my-agent",
        chunking_strategy="bad_val",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=10,
    )
    with pytest.raises(AgentConfigInvalidError) as exc_info:
        await create_agent(request, TENANT_ID, db)

    msg = str(exc_info.value)
    assert "chunking_strategy" in msg
    assert "'bad_val'" in msg
    assert "Supported values" in msg


@pytest.mark.asyncio
async def test_create_agent_cache_enabled_without_threshold() -> None:
    db = make_mock_db(find_one_return=None)
    request = AgentCreateRequest(
        name="my-agent",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=10,
        semantic_cache_enabled=True,
        semantic_cache_threshold=None,
    )
    with pytest.raises(AgentConfigInvalidError) as exc_info:
        await create_agent(request, TENANT_ID, db)

    assert "semantic_cache_threshold" in str(exc_info.value)
    db["agents"].insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_create_agent_cache_enabled_with_threshold_succeeds() -> None:
    db = make_mock_db(find_one_return=None)
    request = AgentCreateRequest(
        name="my-agent",
        chunking_strategy="fixed_size",
        vector_store="pgvector",
        embedding_provider="openai",
        llm_provider="anthropic",
        retrieval_mode="dense",
        reranker="none",
        top_k=10,
        semantic_cache_enabled=True,
        semantic_cache_threshold=0.85,
    )
    result = await create_agent(request, TENANT_ID, db)
    assert result.semantic_cache_enabled is True
    assert result.semantic_cache_threshold == 0.85


# ---------------------------------------------------------------------------
# get_agent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_success() -> None:
    db = make_mock_db(find_one_return=FAKE_AGENT_DOC)
    result = await get_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db)

    assert isinstance(result, AgentDocument)
    assert result.agent_id == FAKE_AGENT_DOC["agent_id"]
    assert result.tenant_id == TENANT_ID
    assert result.name == FAKE_AGENT_DOC["name"]
    assert result.status == "active"


@pytest.mark.asyncio
async def test_get_agent_not_found() -> None:
    db = make_mock_db(find_one_return=None)
    with pytest.raises(AgentNotFoundError):
        await get_agent("nonexistent-id", TENANT_ID, db)


@pytest.mark.asyncio
async def test_get_agent_wrong_tenant() -> None:
    doc = {**FAKE_AGENT_DOC, "tenant_id": "other-tenant"}
    db = make_mock_db(find_one_return=doc)
    with pytest.raises(ForbiddenError):
        await get_agent(FAKE_AGENT_DOC["agent_id"], "caller-id", db)


# ---------------------------------------------------------------------------
# list_agents tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agents_empty() -> None:
    db = make_mock_db(find_return_list=[])
    items, next_cursor = await list_agents(TENANT_ID, db)

    assert items == []
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_agents_with_items() -> None:
    second_oid = ObjectId("507f1f77bcf86cd799439012")
    second_doc = {**FAKE_AGENT_DOC, "agent_id": "507f1f77bcf86cd799439012", "_id": second_oid}
    db = make_mock_db(find_return_list=[FAKE_AGENT_DOC, second_doc])
    items, next_cursor = await list_agents(TENANT_ID, db)

    assert len(items) == 2
    assert all(isinstance(item, AgentDocument) for item in items)
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_agents_pagination_has_more() -> None:
    second_oid = ObjectId("507f1f77bcf86cd799439012")
    second_doc = {**FAKE_AGENT_DOC, "agent_id": "507f1f77bcf86cd799439012", "_id": second_oid}
    db = make_mock_db(find_return_list=[FAKE_AGENT_DOC, second_doc])
    items, next_cursor = await list_agents(TENANT_ID, db, limit=1)

    assert len(items) == 1
    assert next_cursor is not None
    assert isinstance(next_cursor, str)


@pytest.mark.asyncio
async def test_list_agents_invalid_cursor() -> None:
    db = make_mock_db(find_return_list=[])
    with pytest.raises(ValueError):
        await list_agents(TENANT_ID, db, cursor="notvalidbase64!!")


# ---------------------------------------------------------------------------
# update_agent_config tests
# ---------------------------------------------------------------------------

UPDATED_AGENT_DOC = {
    **FAKE_AGENT_DOC,
    "chunking_strategy": "semantic",
    "updated_at": datetime.now(UTC),
}


@pytest.mark.asyncio
async def test_update_agent_config_success_no_field_changes() -> None:
    db = make_mock_db(find_one_return=FAKE_AGENT_DOC)
    result, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"], TENANT_ID, AgentConfigUpdateRequest(), db
    )
    assert isinstance(result, AgentDocument)
    assert warnings == []
    db["agents"].update_one.assert_not_called()


@pytest.mark.asyncio
async def test_update_agent_config_success_updates_field() -> None:
    updated_doc = {**FAKE_AGENT_DOC, "vector_store": "qdrant", "updated_at": datetime.now(UTC)}
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, updated_doc],
        documents_find_one_return=None,
    )
    result, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(vector_store="qdrant"),
        db,
    )
    assert result.vector_store == "qdrant"
    assert warnings == []
    db["agents"].update_one.assert_called_once()


@pytest.mark.asyncio
async def test_update_agent_config_rejects_enabling_cache_without_threshold() -> None:
    db = make_mock_db(find_one_return=FAKE_AGENT_DOC)
    with pytest.raises(AgentConfigInvalidError) as exc_info:
        await update_agent_config(
            FAKE_AGENT_DOC["agent_id"],
            TENANT_ID,
            AgentConfigUpdateRequest(semantic_cache_enabled=True),
            db,
        )

    assert "semantic_cache_threshold" in str(exc_info.value)
    db["agents"].update_one.assert_not_called()


@pytest.mark.asyncio
async def test_update_agent_config_allows_clearing_threshold_when_disabling_cache() -> None:
    existing_doc = {
        **FAKE_AGENT_DOC,
        "semantic_cache_enabled": True,
        "semantic_cache_threshold": 0.85,
    }
    updated_doc = {
        **existing_doc,
        "semantic_cache_enabled": False,
        "semantic_cache_threshold": None,
        "updated_at": datetime.now(UTC),
    }
    db = make_mock_db(agents_find_one_side_effect=[existing_doc, updated_doc])
    result, warnings = await update_agent_config(
        existing_doc["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(
            semantic_cache_enabled=False, semantic_cache_threshold=None
        ),
        db,
    )

    assert result.semantic_cache_enabled is False
    assert result.semantic_cache_threshold is None
    assert warnings == []
    db["agents"].update_one.assert_called_once()
    update_filter, update_payload = db["agents"].update_one.call_args.args
    assert update_filter == {"agent_id": existing_doc["agent_id"]}
    assert update_payload["$set"]["semantic_cache_enabled"] is False
    assert update_payload["$set"]["semantic_cache_threshold"] is None
    assert isinstance(update_payload["$set"]["updated_at"], datetime)


@pytest.mark.asyncio
async def test_update_agent_config_chunking_warning_with_docs() -> None:
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, UPDATED_AGENT_DOC],
        documents_find_one_return={"_id": "some-doc"},
    )
    result, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(chunking_strategy="semantic"),
        db,
    )
    assert len(warnings) == 1
    assert "fixed_size" in warnings[0]
    assert "Re-ingestion required" in warnings[0]


@pytest.mark.asyncio
async def test_update_agent_config_chunking_no_warning_no_docs() -> None:
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, UPDATED_AGENT_DOC],
        documents_find_one_return=None,
    )
    _, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(chunking_strategy="semantic"),
        db,
    )
    assert warnings == []


@pytest.mark.asyncio
async def test_update_agent_config_chunking_no_warning_same_value() -> None:
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, FAKE_AGENT_DOC],
        documents_find_one_return={"_id": "some-doc"},
    )
    _, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(chunking_strategy="fixed_size"),
        db,
    )
    assert warnings == []


@pytest.mark.asyncio
async def test_update_agent_config_embedding_warning_with_docs() -> None:
    updated_doc = {
        **FAKE_AGENT_DOC,
        "embedding_provider": "cohere",
        "updated_at": datetime.now(UTC),
    }
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, updated_doc],
        documents_find_one_return={"_id": "some-doc"},
    )
    _, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(embedding_provider="cohere"),
        db,
    )
    assert len(warnings) == 1
    assert "openai" in warnings[0]
    assert "cohere" in warnings[0]


@pytest.mark.asyncio
async def test_update_agent_config_both_warnings() -> None:
    updated_doc = {
        **FAKE_AGENT_DOC,
        "chunking_strategy": "semantic",
        "embedding_provider": "cohere",
        "updated_at": datetime.now(UTC),
    }
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, updated_doc],
        documents_find_one_return={"_id": "some-doc"},
    )
    _, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(chunking_strategy="semantic", embedding_provider="cohere"),
        db,
    )
    assert len(warnings) == 2


@pytest.mark.asyncio
async def test_update_agent_config_not_found() -> None:
    db = make_mock_db(find_one_return=None)
    with pytest.raises(AgentNotFoundError):
        await update_agent_config(
            "nonexistent-id", TENANT_ID, AgentConfigUpdateRequest(), db
        )
    db["agents"].update_one.assert_not_called()


@pytest.mark.asyncio
async def test_update_agent_config_wrong_tenant() -> None:
    doc = {**FAKE_AGENT_DOC, "tenant_id": "other-tenant"}
    db = make_mock_db(find_one_return=doc)
    with pytest.raises(ForbiddenError):
        await update_agent_config(
            FAKE_AGENT_DOC["agent_id"], TENANT_ID, AgentConfigUpdateRequest(), db
        )
    db["agents"].update_one.assert_not_called()


@pytest.mark.asyncio
async def test_update_agent_config_invalid_chunking_strategy() -> None:
    db = make_mock_db(find_one_return=FAKE_AGENT_DOC)
    with pytest.raises(AgentConfigInvalidError):
        await update_agent_config(
            FAKE_AGENT_DOC["agent_id"],
            TENANT_ID,
            AgentConfigUpdateRequest(chunking_strategy="bad"),
            db,
        )
    db["agents"].update_one.assert_not_called()


# ---------------------------------------------------------------------------
# delete_agent tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_agent_success_no_documents() -> None:
    db = make_mock_db(find_one_return=FAKE_AGENT_DOC, documents_find_one_return=None)
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    db["documents"].delete_many.assert_called_once_with({"agent_id": FAKE_AGENT_DOC["agent_id"]})
    db["agents"].delete_one.assert_called_once_with({"agent_id": FAKE_AGENT_DOC["agent_id"]})
    mock_vs.delete_namespace.assert_called_once()


@pytest.mark.asyncio
async def test_delete_agent_success_calls_correct_namespace() -> None:
    db = make_mock_db(find_one_return=FAKE_AGENT_DOC)
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)
    expected_namespace = f"{FAKE_AGENT_DOC['tenant_id']}_{FAKE_AGENT_DOC['agent_id']}"

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    mock_vs.delete_namespace.assert_called_once_with(expected_namespace)


@pytest.mark.asyncio
async def test_delete_agent_success_with_documents() -> None:
    db = make_mock_db(
        find_one_return=FAKE_AGENT_DOC,
        documents_find_one_return={"doc_id": "x"},
    )
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    db["documents"].delete_many.assert_called_once_with({"agent_id": FAKE_AGENT_DOC["agent_id"]})
    db["agents"].delete_one.assert_called_once()
    mock_vs.delete_namespace.assert_called_once()


@pytest.mark.asyncio
async def test_delete_agent_not_found() -> None:
    db = make_mock_db(find_one_return=None)
    aws_mock = _make_aws_mock()
    settings = _make_settings()

    with pytest.raises(AgentNotFoundError):
        await delete_agent("nonexistent-id", TENANT_ID, db, aws_mock, settings)

    db["agents"].delete_one.assert_not_called()
    db["documents"].delete_many.assert_not_called()


@pytest.mark.asyncio
async def test_delete_agent_wrong_tenant() -> None:
    doc = {**FAKE_AGENT_DOC, "tenant_id": "other-tenant"}
    db = make_mock_db(find_one_return=doc)
    aws_mock = _make_aws_mock()
    settings = _make_settings()

    with pytest.raises(ForbiddenError):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    db["agents"].delete_one.assert_not_called()
    db["documents"].delete_many.assert_not_called()


@pytest.mark.asyncio
async def test_delete_agent_vector_store_key_from_doc() -> None:
    doc = {**FAKE_AGENT_DOC, "vector_store": "qdrant"}
    db = make_mock_db(find_one_return=doc)
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs) as mock_get_vs:
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    mock_get_vs.assert_called_once_with("qdrant")


@pytest.mark.asyncio
async def test_delete_agent_provider_unavailable_no_mongo_deletes() -> None:
    from app.core.errors import ProviderUnavailableError

    db = make_mock_db(find_one_return=FAKE_AGENT_DOC)
    aws_mock = _make_aws_mock()
    settings = _make_settings()

    with patch(
        "app.services.agent_service.get_vector_store",
        side_effect=ProviderUnavailableError("pgvector provider not registered"),
    ), pytest.raises(ProviderUnavailableError):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    db["agents"].delete_one.assert_not_called()
    db["documents"].delete_many.assert_not_called()


@pytest.mark.asyncio
async def test_delete_agent_namespace_failure_no_mongo_deletes() -> None:
    db = make_mock_db(find_one_return=FAKE_AGENT_DOC)
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(side_effect=RuntimeError("vector backend unavailable"))

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs), pytest.raises(
        RuntimeError, match="vector backend unavailable"
    ):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    db["agents"].delete_one.assert_not_called()
    db["documents"].delete_many.assert_not_called()


def test_agent_config_update_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AgentConfigUpdateRequest(**{"vectorstore": "pgvector"})  # type: ignore[arg-type]

    assert "vectorstore" in str(exc_info.value)


# ---------------------------------------------------------------------------
# H1: vector_store mismatch warning tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_agent_config_vector_store_warning_with_docs() -> None:
    updated_doc = {**FAKE_AGENT_DOC, "vector_store": "qdrant", "updated_at": datetime.now(UTC)}
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, updated_doc],
        documents_find_one_return={"_id": "some-doc"},
    )
    _, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(vector_store="qdrant"),
        db,
    )
    assert len(warnings) == 1
    assert "pgvector" in warnings[0]
    assert "qdrant" in warnings[0]
    assert "Re-ingestion" in warnings[0]


@pytest.mark.asyncio
async def test_update_agent_config_vector_store_no_warning_no_docs() -> None:
    updated_doc = {**FAKE_AGENT_DOC, "vector_store": "qdrant", "updated_at": datetime.now(UTC)}
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, updated_doc],
        documents_find_one_return=None,
    )
    _, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(vector_store="qdrant"),
        db,
    )
    assert warnings == []


@pytest.mark.asyncio
async def test_update_agent_config_vector_store_no_warning_same_value() -> None:
    db = make_mock_db(
        agents_find_one_side_effect=[FAKE_AGENT_DOC, FAKE_AGENT_DOC],
        documents_find_one_return={"_id": "some-doc"},
    )
    _, warnings = await update_agent_config(
        FAKE_AGENT_DOC["agent_id"],
        TENANT_ID,
        AgentConfigUpdateRequest(vector_store="pgvector"),
        db,
    )
    assert warnings == []


# ---------------------------------------------------------------------------
# H2: delete_agent S3 + DynamoDB cleanup tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_agent_s3_cleanup_for_docs_with_s3_keys() -> None:
    docs_with_s3 = [
        {"s3_key": "t1/a1/d1/file.pdf", "job_id": "job-001"},
        {"s3_key": "t1/a1/d2/file.txt", "job_id": "job-002"},
    ]
    db = make_mock_db(
        find_one_return=FAKE_AGENT_DOC,
        documents_find_return_list=docs_with_s3,
    )
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    s3_client = aws_mock.client("s3").__aenter__.return_value
    s3_client.delete_objects.assert_called_once()
    call_kwargs = s3_client.delete_objects.call_args.kwargs
    assert call_kwargs["Bucket"] == settings.s3_document_bucket
    objects = call_kwargs["Delete"]["Objects"]
    assert len(objects) == 2
    keys = {o["Key"] for o in objects}
    assert "t1/a1/d1/file.pdf" in keys
    assert "t1/a1/d2/file.txt" in keys


@pytest.mark.asyncio
async def test_delete_agent_dynamodb_cleanup_for_docs_with_job_ids() -> None:
    docs_with_jobs = [
        {"s3_key": "t1/a1/d1/file.pdf", "job_id": "job-001"},
        {"s3_key": "t1/a1/d2/file.txt", "job_id": "job-002"},
    ]
    db = make_mock_db(
        find_one_return=FAKE_AGENT_DOC,
        documents_find_return_list=docs_with_jobs,
    )
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    dynamo_client = aws_mock.client("dynamodb").__aenter__.return_value
    assert dynamo_client.delete_item.call_count == 2
    call_keys = {
        dynamo_client.delete_item.call_args_list[i].kwargs["Key"]["job_id"]["S"]
        for i in range(2)
    }
    assert call_keys == {"job-001", "job-002"}


@pytest.mark.asyncio
async def test_delete_agent_no_s3_or_dynamo_when_no_docs() -> None:
    db = make_mock_db(
        find_one_return=FAKE_AGENT_DOC,
        documents_find_return_list=[],
    )
    aws_mock = _make_aws_mock()
    settings = _make_settings()
    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.agent_service.get_vector_store", return_value=mock_vs):
        await delete_agent(FAKE_AGENT_DOC["agent_id"], TENANT_ID, db, aws_mock, settings)

    s3_client = aws_mock.client("s3").__aenter__.return_value
    s3_client.delete_objects.assert_not_called()
    dynamo_client = aws_mock.client("dynamodb").__aenter__.return_value
    dynamo_client.delete_item.assert_not_called()
