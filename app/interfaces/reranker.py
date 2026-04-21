from abc import ABC, abstractmethod

from app.models.chunk import Chunk


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]: ...
