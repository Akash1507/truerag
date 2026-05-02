from unittest.mock import AsyncMock, MagicMock

import pytest

from app.providers.cache import semantic_cache


@pytest.mark.asyncio
async def test_lookup_returns_none_on_miss() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    semantic_cache._get_pool = AsyncMock(return_value=pool)  # type: ignore[assignment]

    result = await semantic_cache.lookup("agent-1", [0.1, 0.2], 0.9)

    assert result is None


@pytest.mark.asyncio
async def test_lookup_returns_response_on_hit() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value="cached answer")
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    semantic_cache._get_pool = AsyncMock(return_value=pool)  # type: ignore[assignment]

    result = await semantic_cache.lookup("agent-1", [0.1, 0.2], 0.8)

    assert result == "cached answer"


@pytest.mark.asyncio
async def test_lookup_returns_none_below_threshold() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    semantic_cache._get_pool = AsyncMock(return_value=pool)  # type: ignore[assignment]

    result = await semantic_cache.lookup("agent-1", [0.5, 0.6], 0.95)

    assert result is None


@pytest.mark.asyncio
async def test_store_inserts_row() -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    semantic_cache._get_pool = AsyncMock(return_value=pool)  # type: ignore[assignment]

    await semantic_cache.store("agent-1", [0.1, 0.2], "hash", "resp")

    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalidate_deletes_by_agent_id() -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="DELETE 3")
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    semantic_cache._get_pool = AsyncMock(return_value=pool)  # type: ignore[assignment]

    await semantic_cache.invalidate("agent-1")

    conn.execute.assert_awaited_once_with("DELETE FROM semantic_cache WHERE agent_id = $1", "agent-1")


@pytest.mark.asyncio
async def test_cleanup_expired_entries_returns_count() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=4)
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    semantic_cache._get_pool = AsyncMock(return_value=pool)  # type: ignore[assignment]

    deleted = await semantic_cache.cleanup_expired_entries(24)

    assert deleted == 4
