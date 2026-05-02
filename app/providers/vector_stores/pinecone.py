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
        self, namespace: str, vector: list[float], top_k: int, filters: dict[str, str] | None
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
            results.append(
                VectorResult(
                    id=str(match.id),
                    score=float(match.score),
                    metadata=ChunkMetadata.model_validate(metadata),
                    text=text,
                )
            )
        return results

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
