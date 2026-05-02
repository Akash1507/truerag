from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.errors import NamespaceViolationError
from app.models.chunk import ChunkMetadata, VectorRecord, VectorResult
from app.providers.vector_stores.pinecone import PineconeVectorStore
from app.providers.vector_stores.pgvector import PgVectorStore
from app.providers.vector_stores.qdrant import QdrantVectorStore


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
@pytest.mark.parametrize("store_cls", [PgVectorStore, QdrantVectorStore, PineconeVectorStore])
async def test_vector_store_contract_upsert_then_query_returns_results(
    store_cls: type[PgVectorStore] | type[QdrantVectorStore] | type[PineconeVectorStore],
) -> None:
    store = store_cls()
    store.upsert = AsyncMock(return_value=None)  # type: ignore[method-assign]
    store.query = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            VectorResult(
                id="doc-1_0",
                score=0.99,
                metadata=_metadata(),
                text="chunk text",
            )
        ]
    )

    vectors = [VectorRecord(id="doc-1_0", vector=[0.1, 0.2], metadata=_metadata(), text="chunk text")]
    await store.upsert("tenant-1_agent-1", vectors)
    result = await store.query("tenant-1_agent-1", [0.1, 0.2], 1, None)

    assert len(result) == 1


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("store_cls", [PgVectorStore, QdrantVectorStore, PineconeVectorStore])
async def test_vector_store_contract_delete_namespace(
    store_cls: type[PgVectorStore] | type[QdrantVectorStore] | type[PineconeVectorStore],
) -> None:
    store = store_cls()

    if isinstance(store, PgVectorStore):
        conn = AsyncMock()
        acquire_ctx = AsyncMock()
        acquire_ctx.__aenter__.return_value = conn
        pool = MagicMock()
        pool.acquire.return_value = acquire_ctx
        store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

        await store.delete_namespace("tenant-1_agent-1")

        conn.execute.assert_awaited_once()
        return

    if isinstance(store, QdrantVectorStore):
        client = AsyncMock()
        store._get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]
        await store.delete_namespace("tenant-1_agent-1")
        client.delete_collection.assert_awaited_once_with(collection_name="tenant-1_agent-1")
        return

    index = MagicMock()
    store._get_index = AsyncMock(return_value=index)  # type: ignore[method-assign]
    await store.delete_namespace("tenant-1_agent-1")
    index.delete.assert_called_once_with(delete_all=True, namespace="tenant-1_agent-1")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("store_cls", [PgVectorStore, QdrantVectorStore, PineconeVectorStore])
async def test_vector_store_contract_health_returns_true_when_available(
    store_cls: type[PgVectorStore] | type[QdrantVectorStore] | type[PineconeVectorStore],
) -> None:
    store = store_cls()

    if isinstance(store, PgVectorStore):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        acquire_ctx = AsyncMock()
        acquire_ctx.__aenter__.return_value = conn
        pool = MagicMock()
        pool.acquire.return_value = acquire_ctx
        store._get_pool = AsyncMock(return_value=pool)  # type: ignore[method-assign]

        assert await store.health() is True
        return

    if isinstance(store, QdrantVectorStore):
        client = AsyncMock()
        client.get_collections = AsyncMock(return_value=MagicMock())
        store._get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]
        assert await store.health() is True
        return

    index = MagicMock()
    index.describe_index_stats.return_value = {"namespaces": {}}
    store._get_index = AsyncMock(return_value=index)  # type: ignore[method-assign]
    assert await store.health() is True


@pytest.mark.asyncio
async def test_qdrant_upsert_calls_client_upsert() -> None:
    store = QdrantVectorStore()
    client = AsyncMock()
    client.collection_exists = AsyncMock(return_value=True)
    store._get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]

    vectors = [VectorRecord(id="doc-1_0", vector=[0.1, 0.2], metadata=_metadata(), text="chunk text")]
    await store.upsert("tenant-1_agent-1", vectors)

    client.upsert.assert_awaited_once()
    _, kwargs = client.upsert.await_args
    assert kwargs["collection_name"] == "tenant-1_agent-1"


@pytest.mark.asyncio
async def test_qdrant_query_namespace_violation() -> None:
    store = QdrantVectorStore()
    client = AsyncMock()
    hit = MagicMock()
    hit.id = "doc-1_0"
    hit.score = 0.9
    hit.payload = {
        "namespace": "tenant-2_agent-9",
        "text": "chunk text",
        "metadata": _metadata().model_dump(mode="json"),
    }
    client.query_points = AsyncMock(return_value=MagicMock(points=[hit]))
    store._get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]

    with pytest.raises(NamespaceViolationError):
        await store.query("tenant-1_agent-1", [0.1, 0.2], 1, None)


@pytest.mark.asyncio
async def test_qdrant_health_returns_false_on_exception() -> None:
    store = QdrantVectorStore()
    client = AsyncMock()
    client.get_collections = AsyncMock(side_effect=RuntimeError("down"))
    store._get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]

    assert await store.health() is False


@pytest.mark.asyncio
async def test_pinecone_upsert_passes_namespace() -> None:
    store = PineconeVectorStore()
    index = MagicMock()
    store._get_index = AsyncMock(return_value=index)  # type: ignore[method-assign]

    vectors = [VectorRecord(id="doc-1_0", vector=[0.1, 0.2], metadata=_metadata(), text="chunk text")]
    await store.upsert("tenant-1_agent-1", vectors)

    index.upsert.assert_called_once()
    _, kwargs = index.upsert.call_args
    assert kwargs["namespace"] == "tenant-1_agent-1"


@pytest.mark.asyncio
async def test_pinecone_query_namespace_violation() -> None:
    store = PineconeVectorStore()
    index = MagicMock()
    match = MagicMock()
    match.id = "doc-1_0"
    match.score = 0.9
    match.metadata = {
        "namespace": "tenant-2_agent-9",
        "text": "chunk text",
        **_metadata().model_dump(mode="json"),
    }
    index.query.return_value = MagicMock(matches=[match])
    store._get_index = AsyncMock(return_value=index)  # type: ignore[method-assign]

    with pytest.raises(NamespaceViolationError):
        await store.query("tenant-1_agent-1", [0.1, 0.2], 1, None)


@pytest.mark.asyncio
async def test_pinecone_health_returns_false_on_exception() -> None:
    store = PineconeVectorStore()
    index = MagicMock()
    index.describe_index_stats.side_effect = RuntimeError("down")
    store._get_index = AsyncMock(return_value=index)  # type: ignore[method-assign]

    assert await store.health() is False
