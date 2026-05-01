from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import NamespaceViolationError
from app.models.chunk import ChunkMetadata, VectorRecord
from app.providers.vector_stores.pgvector import PgVectorStore


def _metadata() -> ChunkMetadata:
    return ChunkMetadata(
        tenant_id="tenant-123",
        agent_id="agent-456",
        document_id="doc-789",
        chunk_index=0,
        chunking_strategy="fixed_size",
        timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
        version=1,
    )


@pytest.fixture(autouse=True)
def reset_pgvector_store_state() -> None:
    PgVectorStore._pool = None
    PgVectorStore._pool_lock = None


@pytest.mark.asyncio
async def test_upsert_persists_namespace_and_metadata() -> None:
    store = PgVectorStore()
    conn = AsyncMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

    vectors = [
        VectorRecord(id="doc-789_0", vector=[0.1, 0.2], metadata=_metadata(), text="a"),
        VectorRecord(
            id="doc-789_1",
            vector=[0.3, 0.4],
            metadata=_metadata().model_copy(update={"chunk_index": 1}),
            text="b",
        ),
    ]
    await store.upsert(namespace="tenant-123_agent-456", vectors=vectors)

    conn.executemany.assert_awaited_once()
    payload = conn.executemany.await_args.args[1]
    assert len(payload) == 2
    assert payload[0][1] == "tenant-123_agent-456"


@pytest.mark.asyncio
async def test_query_namespace_filter_and_metadata_filter_applied() -> None:
    store = PgVectorStore()
    conn = AsyncMock()
    conn.fetch.return_value = []
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

    await store.query(
        namespace="tenant-123_agent-456",
        vector=[0.1, 0.2],
        top_k=5,
        filters={"document_id": "doc-789"},
    )

    sql = conn.fetch.await_args.args[0]
    params = conn.fetch.await_args.args[1:]
    assert "WHERE namespace = $1" in sql
    assert "metadata ->>" in sql
    assert params[0] == "tenant-123_agent-456"
    assert params[-1] == 5


@pytest.mark.asyncio
async def test_cross_namespace_row_raises_violation() -> None:
    store = PgVectorStore()
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "id": "doc-789_0",
            "namespace": "wrong_namespace",
            "metadata": _metadata().model_dump(mode="json"),
            "text": "chunk",
            "distance": 0.1,
        }
    ]
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

    with patch("app.providers.vector_stores.pgvector.logger") as mock_logger:
        with pytest.raises(NamespaceViolationError):
            await store.query("tenant-123_agent-456", [0.1, 0.2], 5, None)
    mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_delete_namespace_scopes_delete_to_namespace() -> None:
    store = PgVectorStore()
    conn = AsyncMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

    await store.delete_namespace("tenant-123_agent-456")

    conn.execute.assert_awaited_once()
    sql, namespace = conn.execute.await_args.args
    assert "WHERE namespace = $1" in sql
    assert namespace == "tenant-123_agent-456"


@pytest.mark.asyncio
async def test_delete_document_scopes_delete_to_namespace_and_document() -> None:
    store = PgVectorStore()
    conn = AsyncMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

    await store.delete_document("tenant-123_agent-456", "doc-789")

    conn.execute.assert_awaited_once()
    sql, namespace, document_id = conn.execute.await_args.args
    assert "WHERE namespace = $1 AND document_id = $2" in sql
    assert namespace == "tenant-123_agent-456"
    assert document_id == "doc-789"


@pytest.mark.asyncio
async def test_pool_initialized_once_across_instances() -> None:
    conn = AsyncMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx

    with patch(
        "app.providers.vector_stores.pgvector.asyncpg.create_pool",
        AsyncMock(return_value=pool),
    ) as mock_create_pool:
        first = PgVectorStore()
        second = PgVectorStore()

        first_pool = await first._get_pool()
        second_pool = await second._get_pool()

    assert first_pool is pool
    assert second_pool is pool
    mock_create_pool.assert_awaited_once()
    conn.execute.assert_awaited_once()
