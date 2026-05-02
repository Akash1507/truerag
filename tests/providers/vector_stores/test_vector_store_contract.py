from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.chunk import ChunkMetadata, VectorRecord
from app.providers.vector_stores.pgvector import PgVectorStore


def _metadata() -> ChunkMetadata:
    return ChunkMetadata(
        tenant_id="tenant-1",
        agent_id="agent-1",
        document_id="doc-1",
        chunk_index=0,
        chunking_strategy="fixed_size",
        timestamp=datetime.now(UTC),
        version=1,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_store_contract_upsert_then_query_returns_results() -> None:
    store = PgVectorStore()
    store.upsert = AsyncMock(return_value=None)  # type: ignore[method-assign]
    store.query = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {
                "id": "doc-1_0",
                "score": 0.99,
                "metadata": _metadata(),
                "text": "chunk text",
            }
        ]
    )

    vectors = [VectorRecord(id="doc-1_0", vector=[0.1, 0.2], metadata=_metadata(), text="chunk text")]
    await store.upsert("tenant-1_agent-1", vectors)
    result = await store.query("tenant-1_agent-1", [0.1, 0.2], 1, None)

    assert len(result) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_store_contract_delete_namespace() -> None:
    store = PgVectorStore()
    conn = AsyncMock()
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

    await store.delete_namespace("tenant-1_agent-1")

    conn.execute.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_store_contract_health_returns_true_when_available() -> None:
    store = PgVectorStore()
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

    assert await store.health() is True
