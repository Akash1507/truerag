from unittest.mock import AsyncMock, MagicMock

import pytest

from app.providers.vector_stores.pgvector import PgVectorStore


@pytest.fixture(autouse=True)
def reset_pgvector_store_state() -> None:
    PgVectorStore._pool = None
    PgVectorStore._pool_lock = None


@pytest.mark.asyncio
async def test_list_hashes_returns_non_empty_hashes_for_namespace() -> None:
    store = PgVectorStore()
    conn = AsyncMock()
    conn.fetch.return_value = [
        {"content_hash": "hash_a"},
        {"content_hash": None},
        {"content_hash": "hash_b"},
    ]
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

    result = await store.list_hashes("tenant-123_agent-456")

    assert result == {"hash_a", "hash_b"}
    sql, namespace = conn.fetch.await_args.args
    assert "metadata->>'content_hash'" in sql
    assert "WHERE namespace = $1" in sql
    assert namespace == "tenant-123_agent-456"
