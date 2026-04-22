import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app.core.errors import TenantAlreadyExistsError, TenantNotFoundError
from app.services.tenant_service import create_tenant, delete_tenant, list_tenants
from app.utils.pagination import encode_cursor


def make_mock_db(find_one_return: dict | None = None) -> MagicMock:
    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=find_one_return)
    mock_collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id="abc"))
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    return mock_db


def make_mock_db_with_collections(
    tenants_find_one: dict | None = None,
    tenants_find_docs: list[dict] | None = None,
    agents_find_docs: list[dict] | None = None,
) -> MagicMock:
    """DB mock with separate tenants and agents collections."""
    if tenants_find_docs is None:
        tenants_find_docs = []
    if agents_find_docs is None:
        agents_find_docs = []

    tenant_cursor = MagicMock()
    tenant_cursor.sort = MagicMock(return_value=tenant_cursor)
    tenant_cursor.limit = MagicMock(return_value=tenant_cursor)
    tenant_cursor.to_list = AsyncMock(return_value=tenants_find_docs)

    tenants_col = MagicMock()
    tenants_col.find_one = AsyncMock(return_value=tenants_find_one)
    tenants_col.find = MagicMock(return_value=tenant_cursor)
    tenants_col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

    agent_cursor = MagicMock()
    agent_cursor.to_list = AsyncMock(return_value=agents_find_docs)

    agents_col = MagicMock()
    agents_col.find = MagicMock(return_value=agent_cursor)
    agents_col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=len(agents_find_docs)))

    def get_item(name: str) -> MagicMock:
        if name == "tenants":
            return tenants_col
        if name == "agents":
            return agents_col
        return MagicMock()

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=get_item)
    mock_db._tenants_col = tenants_col
    mock_db._agents_col = agents_col
    return mock_db


# ---------------------------------------------------------------------------
# create_tenant tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_tenant_success() -> None:
    db = make_mock_db(find_one_return=None)
    tenant, raw_key = await create_tenant("acme", db)

    assert tenant.tenant_id
    assert tenant.name == "acme"
    assert tenant.api_key_hash
    assert tenant.rate_limit_rpm is not None
    assert isinstance(tenant.created_at, datetime)
    assert raw_key
    assert len(raw_key) > 0


@pytest.mark.asyncio
async def test_create_tenant_duplicate_raises_error() -> None:
    existing_doc = {
        "tenant_id": "existing-id",
        "name": "acme",
        "api_key_hash": "somehash",
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC),
    }
    db = make_mock_db(find_one_return=existing_doc)

    with pytest.raises(TenantAlreadyExistsError):
        await create_tenant("acme", db)


@pytest.mark.asyncio
async def test_create_tenant_api_key_hash_is_sha256_of_raw_key() -> None:
    db = make_mock_db(find_one_return=None)
    tenant, raw_key = await create_tenant("acme", db)

    expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    assert tenant.api_key_hash == expected_hash


@pytest.mark.asyncio
async def test_create_tenant_raw_key_not_stored_in_document() -> None:
    db = make_mock_db(find_one_return=None)
    tenant, raw_key = await create_tenant("acme", db)

    collection = db["tenants"]
    call_args = collection.insert_one.call_args
    stored_doc: dict = call_args[0][0]
    assert raw_key not in stored_doc.values()
    assert "api_key" not in stored_doc


@pytest.mark.asyncio
async def test_create_tenant_stored_doc_has_no_raw_key_field() -> None:
    db = make_mock_db(find_one_return=None)
    _, raw_key = await create_tenant("acme", db)

    collection = db["tenants"]
    stored_doc: dict = collection.insert_one.call_args[0][0]
    assert "api_key" not in stored_doc
    assert stored_doc.get("api_key_hash") != raw_key


@pytest.mark.asyncio
async def test_create_tenant_uses_utc_datetime() -> None:
    db = make_mock_db(find_one_return=None)
    before = datetime.now(UTC)
    tenant, _ = await create_tenant("acme", db)
    after = datetime.now(UTC)

    assert tenant.created_at.tzinfo is not None
    assert before <= tenant.created_at <= after


@pytest.mark.asyncio
async def test_create_tenant_error_message_includes_name() -> None:
    existing_doc = {
        "tenant_id": "existing-id",
        "name": "my-team",
        "api_key_hash": "hash",
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC),
    }
    db = make_mock_db(find_one_return=existing_doc)

    with pytest.raises(TenantAlreadyExistsError) as exc_info:
        await create_tenant("my-team", db)

    assert "my-team" in str(exc_info.value)


# ---------------------------------------------------------------------------
# list_tenants tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tenants_empty_db() -> None:
    db = make_mock_db_with_collections(tenants_find_docs=[])
    items, next_cursor = await list_tenants(db, cursor=None, limit=20)

    assert items == []
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_tenants_single_tenant() -> None:
    oid = ObjectId()
    docs = [
        {
            "_id": oid,
            "tenant_id": "t1",
            "name": "acme",
            "rate_limit_rpm": 60,
            "created_at": datetime.now(UTC),
        }
    ]
    db = make_mock_db_with_collections(tenants_find_docs=docs)
    items, next_cursor = await list_tenants(db, cursor=None, limit=20)

    assert len(items) == 1
    assert items[0].tenant_id == "t1"
    assert items[0].name == "acme"
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_tenants_cursor_pagination() -> None:
    limit = 2
    oids = [ObjectId() for _ in range(limit + 1)]
    docs = [
        {
            "_id": oid,
            "tenant_id": f"t{i}",
            "name": f"tenant-{i}",
            "rate_limit_rpm": 60,
            "created_at": datetime.now(UTC),
        }
        for i, oid in enumerate(oids)
    ]
    db = make_mock_db_with_collections(tenants_find_docs=docs)
    items, next_cursor = await list_tenants(db, cursor=None, limit=limit)

    assert len(items) == limit
    assert next_cursor is not None
    expected_cursor = encode_cursor(oids[limit - 1])
    assert next_cursor == expected_cursor


@pytest.mark.asyncio
async def test_list_tenants_invalid_cursor_raises_value_error() -> None:
    db = make_mock_db_with_collections(tenants_find_docs=[])
    with pytest.raises(ValueError, match="Invalid cursor"):
        await list_tenants(db, cursor="!!!invalid!!!", limit=20)


# ---------------------------------------------------------------------------
# delete_tenant tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_tenant_success_no_agents() -> None:
    tenant_doc = {
        "_id": ObjectId(),
        "tenant_id": "t1",
        "name": "acme",
        "api_key_hash": "hash",
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC),
    }
    db = make_mock_db_with_collections(tenants_find_one=tenant_doc, agents_find_docs=[])
    await delete_tenant("t1", db)

    db._tenants_col.delete_one.assert_called_once_with({"tenant_id": "t1"})
    db._agents_col.delete_many.assert_called_once_with({"tenant_id": "t1"})


@pytest.mark.asyncio
async def test_delete_tenant_not_found_raises_error() -> None:
    db = make_mock_db_with_collections(tenants_find_one=None)
    with pytest.raises(TenantNotFoundError):
        await delete_tenant("nonexistent", db)


@pytest.mark.asyncio
async def test_delete_tenant_with_agents_calls_delete_namespace() -> None:
    tenant_doc = {
        "_id": ObjectId(),
        "tenant_id": "t1",
        "name": "acme",
        "api_key_hash": "hash",
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC),
    }
    agent_docs = [
        {"agent_id": "agent-1", "tenant_id": "t1", "vector_store": "pgvector"},
        {"agent_id": "agent-2", "tenant_id": "t1", "vector_store": "pgvector"},
    ]
    db = make_mock_db_with_collections(tenants_find_one=tenant_doc, agents_find_docs=agent_docs)

    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch("app.services.tenant_service.get_vector_store", return_value=mock_vs):
        await delete_tenant("t1", db)

    mock_vs.delete_namespace.assert_any_call("t1_agent-1")
    mock_vs.delete_namespace.assert_any_call("t1_agent-2")
    assert mock_vs.delete_namespace.call_count == 2


@pytest.mark.asyncio
async def test_delete_tenant_deletion_order_agents_before_tenant() -> None:
    """Verify agents are deleted before the tenant document."""
    tenant_doc = {
        "_id": ObjectId(),
        "tenant_id": "t1",
        "name": "acme",
        "api_key_hash": "hash",
        "rate_limit_rpm": 60,
        "created_at": datetime.now(UTC),
    }
    db = make_mock_db_with_collections(tenants_find_one=tenant_doc, agents_find_docs=[])

    call_order: list[str] = []
    original_delete_many = db._agents_col.delete_many

    async def tracked_delete_many(*args: object, **kwargs: object) -> object:
        call_order.append("delete_many_agents")
        return await original_delete_many(*args, **kwargs)

    original_delete_one = db._tenants_col.delete_one

    async def tracked_delete_one(*args: object, **kwargs: object) -> object:
        call_order.append("delete_one_tenant")
        return await original_delete_one(*args, **kwargs)

    db._agents_col.delete_many = tracked_delete_many
    db._tenants_col.delete_one = tracked_delete_one

    await delete_tenant("t1", db)

    assert call_order == ["delete_many_agents", "delete_one_tenant"]
