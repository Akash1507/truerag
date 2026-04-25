from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.errors import (
    AgentAlreadyExistsError,
    AgentConfigInvalidError,
    AgentNotFoundError,
    ForbiddenError,
)
from app.models.agent import AgentCreateRequest, AgentDocument
from app.services.agent_service import create_agent, get_agent, list_agents

TENANT_ID = "test-tenant-id"

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
) -> MagicMock:
    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=find_one_return)
    if insert_raises is not None:
        mock_collection.insert_one = AsyncMock(side_effect=insert_raises)
    else:
        mock_collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake-oid"))

    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=find_return_list or [])
    mock_collection.find = MagicMock(return_value=mock_cursor)

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
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
