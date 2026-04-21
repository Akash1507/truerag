from abc import ABC, abstractmethod

from app.models.chunk import Chunk, ChunkMetadata


class ChunkingStrategy(ABC):
    @abstractmethod
    def chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]: ...
