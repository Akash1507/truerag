from __future__ import annotations

from typing import Any

import tiktoken

from app.interfaces.chunking_strategy import ChunkingStrategy
from app.models.chunk import Chunk, ChunkMetadata


class HierarchicalChunker(ChunkingStrategy):
    def __init__(
        self,
        parent_chunk_tokens: int = 1024,
        child_chunk_tokens: int = 256,
        child_overlap: int = 25,
        **kwargs: Any,
    ) -> None:
        self.parent_chunk_tokens = kwargs.get("chunk_size", parent_chunk_tokens)
        self.child_chunk_tokens = child_chunk_tokens
        self.child_overlap = kwargs.get("chunk_overlap", child_overlap)
        if self.child_overlap >= self.child_chunk_tokens:
            raise ValueError(
                f"child_overlap ({self.child_overlap}) must be < child_chunk_tokens ({self.child_chunk_tokens})"
            )
        self._enc = tiktoken.get_encoding("cl100k_base")

    def _split_parent_windows(self, tokens: list[int]) -> list[list[int]]:
        return [
            tokens[start : start + self.parent_chunk_tokens]
            for start in range(0, len(tokens), self.parent_chunk_tokens)
        ]

    def chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]:
        if not text or not text.strip():
            return []

        all_tokens = self._enc.encode(text)
        parent_windows = self._split_parent_windows(all_tokens)
        child_stride = self.child_chunk_tokens - self.child_overlap
        chunks: list[Chunk] = []
        global_index = 0

        for parent_tokens in parent_windows:
            parent_text = self._enc.decode(parent_tokens)
            for child_start in range(0, len(parent_tokens), child_stride):
                child_tokens = parent_tokens[child_start : child_start + self.child_chunk_tokens]
                if not child_tokens:
                    continue
                chunks.append(
                    Chunk(
                        text=self._enc.decode(child_tokens),
                        metadata=ChunkMetadata(
                            tenant_id=metadata.tenant_id,
                            agent_id=metadata.agent_id,
                            document_id=metadata.document_id,
                            chunk_index=global_index,
                            chunking_strategy="hierarchical",
                            timestamp=metadata.timestamp,
                            version=metadata.version,
                            parent_text=parent_text,
                        ),
                    )
                )
                global_index += 1
        return chunks
