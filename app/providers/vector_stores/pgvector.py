import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import asyncpg
from pgvector.asyncpg import register_vector

from app.core.config import get_settings
from app.core.errors import NamespaceViolationError, ProviderUnavailableError
from app.interfaces.vector_store import VectorStore
from app.models.chunk import ChunkMetadata, VectorRecord, VectorResult
from app.utils.observability import get_logger

logger = get_logger(__name__)


def _parse_jsonb(raw: object) -> dict:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw  # type: ignore[return-value]


class PgVectorStore(VectorStore):
    _pool: asyncpg.Pool | None = None
    _pool_lock: asyncio.Lock | None = None

    def __init__(self) -> None:
        self._settings = get_settings()
        self._table_name = "document_vectors"

    async def upsert(self, namespace: str, vectors: list[VectorRecord]) -> None:
        if not vectors:
            return
        pool = await self._get_pool()
        sql = f"""
            INSERT INTO {self._table_name}
                (id, namespace, embedding, metadata, text, document_id, chunk_index, created_at, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9)
            ON CONFLICT (id, namespace) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                text = EXCLUDED.text,
                document_id = EXCLUDED.document_id,
                chunk_index = EXCLUDED.chunk_index,
                updated_at = EXCLUDED.updated_at
        """
        now = datetime.now(UTC)
        payload = [
            (
                record.id,
                namespace,
                record.vector,
                json.dumps(record.metadata.model_dump(mode="json")),
                record.text,
                record.metadata.document_id,
                record.metadata.chunk_index,
                now,
                now,
            )
            for record in vectors
        ]
        try:
            async with pool.acquire() as conn:
                await conn.executemany(sql, payload)
        except Exception as exc:
            raise ProviderUnavailableError(f"pgvector upsert failed: {exc}") from exc

    async def query(
        self, namespace: str, vector: list[float], top_k: int, filters: dict[str, str] | None
    ) -> list[VectorResult]:
        pool = await self._get_pool()
        sql = f"""
            SELECT id, namespace, metadata, text, embedding <=> $2::vector AS distance
            FROM {self._table_name}
            WHERE namespace = $1
        """
        params: list[Any] = [namespace, vector]
        next_param = 3
        if filters:
            for key, value in filters.items():
                sql += f" AND metadata ->> ${next_param} = ${next_param + 1}"
                params.extend([key, value])
                next_param += 2
        sql += f" ORDER BY embedding <=> $2::vector LIMIT ${next_param}"
        params.append(top_k)

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception as exc:
            raise ProviderUnavailableError(f"pgvector query failed: {exc}") from exc

        results: list[VectorResult] = []
        for row in rows:
            row_namespace = row["namespace"]
            metadata_dict = _parse_jsonb(row["metadata"])
            if row_namespace != namespace:
                tenant_id = str(metadata_dict.get("tenant_id", "unknown"))
                agent_id = str(metadata_dict.get("agent_id", "unknown"))
                logger.error(
                    "namespace_violation",
                    extra={
                        "operation": "vector_query",
                        "extra_data": {
                            "provider": "pgvector",
                            "tenant_id": tenant_id,
                            "agent_id": agent_id,
                            "requested_namespace": namespace,
                            "returned_namespace": row_namespace,
                        },
                    },
                )
                raise NamespaceViolationError(
                    f"Namespace mismatch: expected={namespace} actual={row_namespace}"
                )
            results.append(
                VectorResult(
                    id=row["id"],
                    score=1.0 - float(row["distance"]),
                    metadata=ChunkMetadata.model_validate(metadata_dict),
                    text=row["text"],
                )
            )
        return results

    async def fetch_all(self, namespace: str, top_k: int) -> list[VectorResult]:
        pool = await self._get_pool()
        sql = f"""
            SELECT id, namespace, metadata, text
            FROM {self._table_name}
            WHERE namespace = $1
            LIMIT $2
        """
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, namespace, top_k)
        except Exception as exc:
            raise ProviderUnavailableError(f"pgvector fetch_all failed: {exc}") from exc

        return [
            VectorResult(
                id=row["id"],
                score=0.0,
                metadata=ChunkMetadata.model_validate(_parse_jsonb(row["metadata"])),
                text=row["text"],
            )
            for row in rows
        ]

    async def delete_namespace(self, namespace: str) -> None:
        pool = await self._get_pool()
        sql = f"DELETE FROM {self._table_name} WHERE namespace = $1"
        try:
            async with pool.acquire() as conn:
                await conn.execute(sql, namespace)
        except Exception as exc:
            raise ProviderUnavailableError(f"pgvector delete failed: {exc}") from exc

    async def delete_document(self, namespace: str, document_id: str) -> None:
        pool = await self._get_pool()
        sql = f"DELETE FROM {self._table_name} WHERE namespace = $1 AND document_id = $2"
        try:
            async with pool.acquire() as conn:
                await conn.execute(sql, namespace, document_id)
        except Exception as exc:
            raise ProviderUnavailableError(f"pgvector delete failed: {exc}") from exc

    async def health(self) -> bool:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def _get_pool(self) -> asyncpg.Pool:
        cls = type(self)
        if cls._pool is not None:
            return cls._pool

        if cls._pool_lock is None:
            cls._pool_lock = asyncio.Lock()

        async with cls._pool_lock:
            if cls._pool is not None:
                return cls._pool
            try:
                # register_vector (pool init callback) fails if the vector type is absent.
                # Pre-create the extension on a throwaway connection before pool creation.
                bootstrap = await asyncpg.connect(dsn=self._settings.pgvector_dsn)
                try:
                    await bootstrap.execute("CREATE EXTENSION IF NOT EXISTS vector")
                finally:
                    await bootstrap.close()

                pool = await asyncpg.create_pool(
                    dsn=self._settings.pgvector_dsn,
                    init=register_vector,
                )
                await self._ensure_schema(pool)
            except Exception as exc:
                raise ProviderUnavailableError(f"pgvector connection failed: {exc}") from exc
            cls._pool = pool
            return pool

    async def _ensure_schema(self, pool: asyncpg.Pool) -> None:
        create_sql = f"""
            CREATE EXTENSION IF NOT EXISTS vector;
            CREATE TABLE IF NOT EXISTS {self._table_name} (
                id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                embedding vector,
                metadata JSONB NOT NULL,
                text TEXT NOT NULL,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (id, namespace)
            );
        """
        async with pool.acquire() as conn:
            await conn.execute(create_sql)
