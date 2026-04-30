import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app.core.errors import TenantAlreadyExistsError, TenantNotFoundError
from app.models.agent import AgentDocument
from app.models.tenant import TenantDocument
from app.services import tenant_service
from app.utils.pagination import encode_cursor


# ---------------------------------------------------------------------------
# create_tenant tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_tenant_success() -> None:
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=None)), patch.object(
        tenant_service.tenant_dao, "insert_one", AsyncMock()
    ):
        tenant, raw_key = await tenant_service.create_tenant("acme")

    assert tenant.tenant_id
    assert tenant.name == "acme"
    assert tenant.api_key_hash
    assert tenant.rate_limit_rpm is not None
    assert isinstance(tenant.created_at, datetime)
    assert raw_key
    assert len(raw_key) > 0


@pytest.mark.asyncio
async def test_create_tenant_duplicate_raises_error() -> None:
    existing_doc = TenantDocument(
        tenant_id="existing-id",
        name="acme",
        api_key_hash="somehash",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=existing_doc)):
        with pytest.raises(TenantAlreadyExistsError):
            await tenant_service.create_tenant("acme")


@pytest.mark.asyncio
async def test_create_tenant_api_key_hash_is_sha256_of_raw_key() -> None:
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=None)), patch.object(
        tenant_service.tenant_dao, "insert_one", AsyncMock()
    ):
        tenant, raw_key = await tenant_service.create_tenant("acme")

    expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    assert tenant.api_key_hash == expected_hash


@pytest.mark.asyncio
async def test_create_tenant_raw_key_not_stored_in_document() -> None:
    insert_mock = AsyncMock()
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=None)), patch.object(
        tenant_service.tenant_dao, "insert_one", insert_mock
    ):
        _, raw_key = await tenant_service.create_tenant("acme")

    stored_doc = insert_mock.call_args.args[0]
    assert raw_key != stored_doc.api_key_hash


@pytest.mark.asyncio
async def test_create_tenant_stored_doc_has_no_raw_key_field() -> None:
    insert_mock = AsyncMock()
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=None)), patch.object(
        tenant_service.tenant_dao, "insert_one", insert_mock
    ):
        _, raw_key = await tenant_service.create_tenant("acme")

    stored_doc = insert_mock.call_args.args[0]
    assert stored_doc.api_key_hash != raw_key


@pytest.mark.asyncio
async def test_create_tenant_uses_utc_datetime() -> None:
    before = datetime.now(UTC)
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=None)), patch.object(
        tenant_service.tenant_dao, "insert_one", AsyncMock()
    ):
        tenant, _ = await tenant_service.create_tenant("acme")
    after = datetime.now(UTC)

    assert tenant.created_at.tzinfo is not None
    assert before <= tenant.created_at <= after


@pytest.mark.asyncio
async def test_create_tenant_error_message_includes_name() -> None:
    existing_doc = TenantDocument(
        tenant_id="existing-id",
        name="my-team",
        api_key_hash="hash",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=existing_doc)):
        with pytest.raises(TenantAlreadyExistsError) as exc_info:
            await tenant_service.create_tenant("my-team")

    assert "my-team" in str(exc_info.value)


# ---------------------------------------------------------------------------
# list_tenants tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tenants_empty_db() -> None:
    with patch.object(tenant_service.tenant_dao, "find", AsyncMock(return_value=[])):
        items, next_cursor = await tenant_service.list_tenants(cursor=None, limit=20)

    assert items == []
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_tenants_single_tenant() -> None:
    oid = ObjectId()
    docs = [
        TenantDocument(
            id=oid,
            tenant_id="t1",
            name="acme",
            api_key_hash="hash",
            rate_limit_rpm=60,
            created_at=datetime.now(UTC),
        )
    ]
    with patch.object(tenant_service.tenant_dao, "find", AsyncMock(return_value=docs)):
        items, next_cursor = await tenant_service.list_tenants(cursor=None, limit=20)

    assert len(items) == 1
    assert items[0].tenant_id == "t1"
    assert items[0].name == "acme"
    assert next_cursor is None


@pytest.mark.asyncio
async def test_list_tenants_cursor_pagination() -> None:
    limit = 2
    oids = [ObjectId() for _ in range(limit + 1)]
    docs = [
        TenantDocument(
            id=oid,
            tenant_id=f"t{i}",
            name=f"tenant-{i}",
            api_key_hash="hash",
            rate_limit_rpm=60,
            created_at=datetime.now(UTC),
        )
        for i, oid in enumerate(oids)
    ]
    with patch.object(tenant_service.tenant_dao, "find", AsyncMock(return_value=docs)):
        items, next_cursor = await tenant_service.list_tenants(cursor=None, limit=limit)

    assert len(items) == limit
    assert next_cursor is not None
    expected_cursor = encode_cursor(oids[limit - 1])
    assert next_cursor == expected_cursor


@pytest.mark.asyncio
async def test_list_tenants_invalid_cursor_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Invalid cursor"):
        await tenant_service.list_tenants(cursor="!!!invalid!!!", limit=20)


# ---------------------------------------------------------------------------
# delete_tenant tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_tenant_success_no_agents() -> None:
    tenant_doc = TenantDocument(
        tenant_id="t1",
        name="acme",
        api_key_hash="hash",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=tenant_doc)), patch.object(
        tenant_service.agent_dao, "find", AsyncMock(return_value=[])
    ), patch.object(tenant_service.agent_dao, "delete_many", AsyncMock()) as delete_agents, patch.object(
        tenant_service.tenant_dao, "delete_one", AsyncMock()
    ) as delete_tenant_doc:
        await tenant_service.delete_tenant("t1")

    delete_tenant_doc.assert_awaited_once_with({"tenant_id": "t1"})
    delete_agents.assert_awaited_once_with({"tenant_id": "t1"})


@pytest.mark.asyncio
async def test_delete_tenant_not_found_raises_error() -> None:
    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=None)):
        with pytest.raises(TenantNotFoundError):
            await tenant_service.delete_tenant("nonexistent")


@pytest.mark.asyncio
async def test_delete_tenant_with_agents_calls_delete_namespace() -> None:
    tenant_doc = TenantDocument(
        tenant_id="t1",
        name="acme",
        api_key_hash="hash",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )
    agent_docs = [
        AgentDocument(
            agent_id="agent-1",
            tenant_id="t1",
            name="a1",
            chunking_strategy="fixed_size",
            vector_store="pgvector",
            embedding_provider="openai",
            llm_provider="anthropic",
            retrieval_mode="dense",
            reranker="none",
            top_k=10,
            semantic_cache_enabled=False,
            semantic_cache_threshold=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        AgentDocument(
            agent_id="agent-2",
            tenant_id="t1",
            name="a2",
            chunking_strategy="fixed_size",
            vector_store="pgvector",
            embedding_provider="openai",
            llm_provider="anthropic",
            retrieval_mode="dense",
            reranker="none",
            top_k=10,
            semantic_cache_enabled=False,
            semantic_cache_threshold=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]

    mock_vs = MagicMock()
    mock_vs.delete_namespace = AsyncMock(return_value=None)

    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=tenant_doc)), patch.object(
        tenant_service.agent_dao, "find", AsyncMock(return_value=agent_docs)
    ), patch.object(tenant_service.agent_dao, "delete_many", AsyncMock()), patch.object(
        tenant_service.tenant_dao, "delete_one", AsyncMock()
    ), patch("app.services.tenant_service.get_vector_store", return_value=mock_vs):
        await tenant_service.delete_tenant("t1")

    mock_vs.delete_namespace.assert_any_call("t1_agent-1")
    mock_vs.delete_namespace.assert_any_call("t1_agent-2")
    assert mock_vs.delete_namespace.call_count == 2


@pytest.mark.asyncio
async def test_delete_tenant_deletion_order_agents_before_tenant() -> None:
    tenant_doc = TenantDocument(
        tenant_id="t1",
        name="acme",
        api_key_hash="hash",
        rate_limit_rpm=60,
        created_at=datetime.now(UTC),
    )

    call_order: list[str] = []

    async def tracked_delete_many(_: dict[str, str]) -> None:
        call_order.append("delete_many_agents")

    async def tracked_delete_one(_: dict[str, str]) -> None:
        call_order.append("delete_one_tenant")

    with patch.object(tenant_service.tenant_dao, "find_one", AsyncMock(return_value=tenant_doc)), patch.object(
        tenant_service.agent_dao, "find", AsyncMock(return_value=[])
    ), patch.object(tenant_service.agent_dao, "delete_many", AsyncMock(side_effect=tracked_delete_many)), patch.object(
        tenant_service.tenant_dao, "delete_one", AsyncMock(side_effect=tracked_delete_one)
    ):
        await tenant_service.delete_tenant("t1")

    assert call_order == ["delete_many_agents", "delete_one_tenant"]
