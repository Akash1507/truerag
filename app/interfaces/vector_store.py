from abc import ABC, abstractmethod

from app.models.chunk import VectorRecord, VectorResult


class VectorStore(ABC):
    @abstractmethod
    async def upsert(self, namespace: str, vectors: list[VectorRecord]) -> None: ...

    @abstractmethod
    async def query(
        self, namespace: str, vector: list[float], top_k: int, filters: dict[str, str] | None
    ) -> list[VectorResult]: ...

    @abstractmethod
    async def delete_namespace(self, namespace: str) -> None: ...

    @abstractmethod
    async def health(self) -> bool: ...
