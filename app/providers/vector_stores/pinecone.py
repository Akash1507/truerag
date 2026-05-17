import asyncio
from typing import Any, cast

from pinecone import Pinecone

from app.core.config import get_settings
from app.core.errors import NamespaceViolationError, ProviderUnavailableError
from app.interfaces.vector_store import VectorStore
from app.models.chunk import ChunkMetadata, VectorRecord, VectorResult
from app.utils.observability import get_logger
from app.utils.secrets import get_secret

logger = get_logger(__name__)


class PineconeVectorStore(VectorStore):
    def __init__(self) -> None:
        self._settings = get_settings()
        self._index: Any | None = None

    async def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        try:
            api_key = await get_secret(self._settings.pinecone_api_key_secret_name)
            client = Pinecone(api_key=api_key)
            self._index = client.Index(self._settings.pinecone_index_name)
            return self._index
        except Exception as exc:
            raise ProviderUnavailableError(f"pinecone index initialization failed: {exc}") from exc

    async def upsert(self, namespace: str, vectors: list[VectorRecord]) -> None:
        if not vectors:
            return
        try:
            index = await self._get_index()
            payload: list[dict[str, object]] = []
            for record in vectors:
                metadata_payload: dict[str, object] = {"namespace": namespace, "text": record.text}
                metadata_payload.update(record.metadata.model_dump(mode="json"))
                payload.append(
                    {
                        "id": record.id,
                        "values": record.vector,
                        "metadata": metadata_payload,
                    }
                )
            await asyncio.to_thread(index.upsert, vectors=payload, namespace=namespace)
        except Exception as exc:
            raise ProviderUnavailableError(f"pinecone upsert failed: {exc}") from exc

    async def query(
        self,
        namespace: str,
        vector: list[float],
        top_k: int,
        filters: dict[str, str] | None,
        include_embeddings: bool = False,
    ) -> list[VectorResult]:
        pinecone_filter: dict[str, dict[str, str]] = {
            "namespace": {"$eq": namespace},
        }
        if filters:
            pinecone_filter.update({key: {"$eq": value} for key, value in filters.items()})
        try:
            index = await self._get_index()
            response = await asyncio.to_thread(
                index.query,
                vector=vector,
                top_k=top_k,
                namespace=namespace,
                filter=pinecone_filter,
                include_metadata=True,
                include_values=include_embeddings,
            )
        except Exception as exc:
            raise ProviderUnavailableError(f"pinecone query failed: {exc}") from exc

        results: list[VectorResult] = []
        for match in response.matches:
            metadata = cast(dict[str, object], match.metadata or {})
            actual_namespace = str(metadata.get("namespace", ""))
            if actual_namespace != namespace:
                logger.error(
                    "namespace_violation",
                    extra={
                        "operation": "vector_query",
                        "extra_data": {
                            "provider": "pinecone",
                            "requested_namespace": namespace,
                            "returned_namespace": actual_namespace,
                        },
                    },
                )
                raise NamespaceViolationError(
                    f"Namespace mismatch: expected={namespace} actual={actual_namespace}"
                )
            text = str(metadata.pop("text", ""))
            metadata.pop("namespace", None)
            embedding: list[float] | None = None
            if include_embeddings:
                raw_values = getattr(match, "values", None)
                if isinstance(raw_values, list):
                    embedding = [float(value) for value in raw_values]
            results.append(
                VectorResult(
                    id=str(match.id),
                    score=float(match.score),
                    metadata=ChunkMetadata.model_validate(metadata),
                    text=text,
                    embedding=embedding,
                )
            )
        return results

    async def fetch_all(self, namespace: str, top_k: int) -> list[VectorResult]:
        try:
            index = await self._get_index()

            def _list_ids() -> list[str]:
                ids: list[str] = []
                for page in index.list(namespace=namespace, limit=100):
                    ids.extend(page)
                    if len(ids) >= top_k:
                        break
                return ids[:top_k]

            ids = await asyncio.to_thread(_list_ids)
            if not ids:
                return []

            results: list[VectorResult] = []
            for i in range(0, len(ids), 100):
                batch = ids[i : i + 100]
                response = await asyncio.to_thread(index.fetch, ids=batch, namespace=namespace)
                for vid, vector_data in response.vectors.items():
                    metadata = cast(dict[str, object], vector_data.metadata or {})
                    actual_namespace = str(metadata.get("namespace", ""))
                    if actual_namespace != namespace:
                        raise NamespaceViolationError(
                            f"Namespace mismatch: expected={namespace} actual={actual_namespace}"
                        )
                    text = str(metadata.pop("text", ""))
                    metadata.pop("namespace", None)
                    results.append(
                        VectorResult(
                            id=vid,
                            score=0.0,
                            metadata=ChunkMetadata.model_validate(metadata),
                            text=text,
                        )
                    )
            return results
        except NamespaceViolationError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(f"pinecone fetch_all failed: {exc}") from exc

    async def list_hashes(self, namespace: str) -> set[str]:
        try:
            index = await self._get_index()

            def _list_ids() -> list[str]:
                ids: list[str] = []
                for page in index.list(namespace=namespace, limit=100):
                    ids.extend(page)
                return ids

            ids = await asyncio.to_thread(_list_ids)
            if not ids:
                return set()

            hashes: set[str] = set()
            for i in range(0, len(ids), 100):
                batch = ids[i : i + 100]
                response = await asyncio.to_thread(index.fetch, ids=batch, namespace=namespace)
                for vector_data in response.vectors.values():
                    metadata = cast(dict[str, object], vector_data.metadata or {})
                    content_hash = metadata.get("content_hash")
                    if content_hash:
                        hashes.add(str(content_hash))
            return hashes
        except Exception as exc:
            raise ProviderUnavailableError(f"pinecone list_hashes failed: {exc}") from exc

    async def delete_namespace(self, namespace: str) -> None:
        try:
            index = await self._get_index()
            await asyncio.to_thread(index.delete, delete_all=True, namespace=namespace)
        except Exception as exc:
            raise ProviderUnavailableError(f"pinecone delete failed: {exc}") from exc

    async def health(self) -> bool:
        try:
            index = await self._get_index()
            await asyncio.to_thread(index.describe_index_stats)
            return True
        except Exception:
            return False
