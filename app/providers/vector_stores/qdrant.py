import hashlib
import uuid
from typing import cast

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import get_settings
from app.core.errors import NamespaceViolationError, ProviderUnavailableError
from app.interfaces.vector_store import VectorStore
from app.models.chunk import ChunkMetadata, VectorRecord, VectorResult
from app.utils.observability import get_logger
from app.utils.secrets import get_secret

logger = get_logger(__name__)


class QdrantVectorStore(VectorStore):
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: AsyncQdrantClient | None = None

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is not None:
            return self._client
        try:
            api_key = await get_secret(self._settings.qdrant_api_key_secret_name)
            self._client = AsyncQdrantClient(url=self._settings.qdrant_url, api_key=api_key)
            return self._client
        except Exception as exc:
            raise ProviderUnavailableError(f"qdrant client initialization failed: {exc}") from exc

    async def upsert(self, namespace: str, vectors: list[VectorRecord]) -> None:
        if not vectors:
            return
        try:
            client = await self._get_client()
            await self._ensure_collection(client, namespace, len(vectors[0].vector))
            points = [
                PointStruct(
                    id=self._to_point_id(record.id),
                    vector=record.vector,
                    payload={
                        "namespace": namespace,
                        "text": record.text,
                        "metadata": record.metadata.model_dump(mode="json"),
                    },
                )
                for record in vectors
            ]
            await client.upsert(collection_name=namespace, points=points)
        except Exception as exc:
            raise ProviderUnavailableError(f"qdrant upsert failed: {exc}") from exc

    async def query(
        self, namespace: str, vector: list[float], top_k: int, filters: dict[str, str] | None
    ) -> list[VectorResult]:
        try:
            client = await self._get_client()
            namespace_filter = {"namespace": namespace}
            merged_filters = namespace_filter | (filters or {})
            search_filter = Filter(
                must=[
                    FieldCondition(key=key, match=MatchValue(value=value))
                    for key, value in merged_filters.items()
                ]
            )
            response = await client.query_points(
                collection_name=namespace,
                query=vector,
                limit=top_k,
                query_filter=search_filter,
            )
        except Exception as exc:
            raise ProviderUnavailableError(f"qdrant query failed: {exc}") from exc

        results: list[VectorResult] = []
        for hit in response.points:
            payload = cast(dict[str, object], hit.payload or {})
            payload_namespace = str(payload.get("namespace", ""))
            if payload_namespace != namespace:
                logger.error(
                    "namespace_violation",
                    extra={
                        "operation": "vector_query",
                        "extra_data": {
                            "provider": "qdrant",
                            "requested_namespace": namespace,
                            "returned_namespace": payload_namespace,
                        },
                    },
                )
                raise NamespaceViolationError(
                    f"Namespace mismatch: expected={namespace} actual={payload_namespace}"
                )
            metadata = ChunkMetadata.model_validate(payload.get("metadata", {}))
            text = str(payload.get("text", ""))
            results.append(
                VectorResult(
                    id=str(hit.id),
                    score=float(hit.score),
                    metadata=metadata,
                    text=text,
                )
            )
        return results

    async def fetch_all(self, namespace: str, top_k: int) -> list[VectorResult]:
        try:
            client = await self._get_client()
            results: list[VectorResult] = []
            offset = None
            while len(results) < top_k:
                batch_limit = min(top_k - len(results), 100)
                points, next_offset = await client.scroll(
                    collection_name=namespace,
                    limit=batch_limit,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = cast(dict[str, object], point.payload or {})
                    metadata = ChunkMetadata.model_validate(payload.get("metadata", {}))
                    text = str(payload.get("text", ""))
                    results.append(VectorResult(id=str(point.id), score=0.0, metadata=metadata, text=text))
                if next_offset is None:
                    break
                offset = next_offset
            return results
        except Exception as exc:
            raise ProviderUnavailableError(f"qdrant fetch_all failed: {exc}") from exc

    async def delete_namespace(self, namespace: str) -> None:
        try:
            client = await self._get_client()
            await client.delete_collection(collection_name=namespace)
        except Exception as exc:
            raise ProviderUnavailableError(f"qdrant delete failed: {exc}") from exc

    async def health(self) -> bool:
        try:
            client = await self._get_client()
            await client.get_collections()
            return True
        except Exception:
            return False

    async def _ensure_collection(
        self, client: AsyncQdrantClient, namespace: str, vector_size: int
    ) -> None:
        exists = await client.collection_exists(collection_name=namespace)
        if exists:
            return
        await client.create_collection(
            collection_name=namespace,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    def _to_point_id(self, source_id: str) -> str:
        return str(uuid.UUID(hashlib.md5(source_id.encode("utf-8")).hexdigest()))
