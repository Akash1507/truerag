import pytest

from app.utils import semantic_cache


@pytest.mark.asyncio
async def test_invalidate_returns_none() -> None:
    result = await semantic_cache.invalidate("tenant-1_agent-abc")
    assert result is None


@pytest.mark.asyncio
async def test_invalidate_empty_string() -> None:
    await semantic_cache.invalidate("")  # must not raise


@pytest.mark.asyncio
async def test_invalidate_is_no_op() -> None:
    await semantic_cache.invalidate("agent-1")
    await semantic_cache.invalidate("agent-1")


@pytest.mark.asyncio
async def test_invalidate_special_chars() -> None:
    await semantic_cache.invalidate("agent/with/slashes?and=params&more")
