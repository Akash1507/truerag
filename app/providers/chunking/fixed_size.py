import tiktoken

from app.interfaces.chunking_strategy import ChunkingStrategy
from app.models.chunk import Chunk, ChunkMetadata


class FixedSizeChunker(ChunkingStrategy):
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50) -> None:
        if chunk_overlap > chunk_size // 2:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be <= chunk_size // 2 ({chunk_size // 2})"
            )
        self._enc = tiktoken.get_encoding("cl100k_base")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]:
        if not text or not text.strip():
            return []
        tokens = self._enc.encode(text)
        chunks: list[Chunk] = []
        stride = self.chunk_size - self.chunk_overlap
        for i, start in enumerate(range(0, len(tokens), stride)):
            window = tokens[start : start + self.chunk_size]
            chunks.append(
                Chunk(
                    text=self._enc.decode(window),
                    metadata=ChunkMetadata(
                        tenant_id=metadata.tenant_id,
                        agent_id=metadata.agent_id,
                        document_id=metadata.document_id,
                        chunk_index=i,
                        chunking_strategy=metadata.chunking_strategy,
                        timestamp=metadata.timestamp,
                        version=metadata.version,
                    ),
                )
            )
        return chunks
