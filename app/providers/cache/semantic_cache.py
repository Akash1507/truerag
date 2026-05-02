import asyncio
from datetime import UTC, datetime
from typing import cast

import asyncpg
from pgvector.asyncpg import register_vector

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.utils.observability import get_logger

logger = get_logger(__name__)

_pool: asyncpg.Pool | None = None
_pool_lock: asyncio.Lock | None = None


async def lookup(agent_id: str, query_vector: list[float], threshold: float) -> str | None:
    if not query_vector:
        return None
    pool = await _get_pool()
    max_distance = 1.0 - threshold
    ttl_hours = get_settings().semantic_cache_ttl_hours
    sql = """
        SELECT response
        FROM semantic_cache
        WHERE agent_id = $1
          AND (embedding <=> $2::vector) <= $3
          AND created_at >= ($4::timestamptz - make_interval(hours => $5::int))
        ORDER BY embedding <=> $2::vector
        LIMIT 1
    """
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                sql, agent_id, query_vector, max_distance, datetime.now(UTC), ttl_hours
            )
            return cast(str | None, result)
    except Exception as exc:
        raise ProviderUnavailableError(f"semantic cache lookup failed: {exc}") from exc


async def store(agent_id: str, query_vector: list[float], query_hash: str, response: str) -> None:
    if not query_vector:
        return
    pool = await _get_pool()
    sql = """
        INSERT INTO semantic_cache (agent_id, embedding, query_hash, response, created_at)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (agent_id, query_hash) DO UPDATE SET
            response = EXCLUDED.response,
            created_at = EXCLUDED.created_at,
            embedding = EXCLUDED.embedding
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(sql, agent_id, query_vector, query_hash, response, datetime.now(UTC))
    except Exception as exc:
        raise ProviderUnavailableError(f"semantic cache store failed: {exc}") from exc


async def invalidate(agent_id: str) -> None:
    pool = await _get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM semantic_cache WHERE agent_id = $1", agent_id)
    except Exception as exc:
        raise ProviderUnavailableError(f"semantic cache invalidate failed: {exc}") from exc


async def cleanup_expired_entries(max_age_hours: int = 24) -> int:
    pool = await _get_pool()
    sql = """
        WITH deleted AS (
            DELETE FROM semantic_cache
            WHERE created_at < ($1::timestamptz - make_interval(hours => $2::int))
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM deleted
    """
    try:
        async with pool.acquire() as conn:
            deleted = await conn.fetchval(sql, datetime.now(UTC), max_age_hours)
            return int(deleted or 0)
    except Exception as exc:
        raise ProviderUnavailableError(f"semantic cache cleanup failed: {exc}") from exc


async def _get_pool() -> asyncpg.Pool:
    global _pool, _pool_lock
    if _pool is not None:
        return _pool

    if _pool_lock is None:
        _pool_lock = asyncio.Lock()

    async with _pool_lock:
        if _pool is not None:
            return _pool
        settings = get_settings()
        try:
            pool = await asyncpg.create_pool(dsn=settings.pgvector_dsn, init=register_vector)
            await _ensure_schema(pool)
        except Exception as exc:
            raise ProviderUnavailableError(f"semantic cache connection failed: {exc}") from exc
        _pool = pool
        return pool


async def _ensure_schema(pool: asyncpg.Pool) -> None:
    sql = """
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS semantic_cache (
            agent_id TEXT NOT NULL,
            embedding vector,
            query_hash TEXT NOT NULL,
            response TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (agent_id, query_hash)
        );
        CREATE INDEX IF NOT EXISTS semantic_cache_agent_idx ON semantic_cache (agent_id);
    """
    async with pool.acquire() as conn:
        await conn.execute(sql)
