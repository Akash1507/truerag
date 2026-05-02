from __future__ import annotations

from typing import Any

import tiktoken

from app.interfaces.chunking_strategy import ChunkingStrategy
from app.models.chunk import Chunk, ChunkMetadata


class KeywordChunker(ChunkingStrategy):
    def __init__(self, max_chunk_tokens: int = 512, **kwargs: Any) -> None:
        self.max_chunk_tokens = kwargs.get("chunk_size", max_chunk_tokens)
        self._enc = tiktoken.get_encoding("cl100k_base")

    def _split_paragraphs(self, text: str) -> list[str]:
        return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]

    def _token_limit(self, paragraph: str) -> list[str]:
        tokens = self._enc.encode(paragraph)
        if len(tokens) <= self.max_chunk_tokens:
            return [paragraph]
        return [
            self._enc.decode(tokens[start : start + self.max_chunk_tokens])
            for start in range(0, len(tokens), self.max_chunk_tokens)
        ]

    def chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]:
        if not text or not text.strip():
            return []

        chunks: list[Chunk] = []
        chunk_index = 0
        for paragraph in self._split_paragraphs(text):
            for chunk_text in self._token_limit(paragraph):
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        metadata=ChunkMetadata(
                            tenant_id=metadata.tenant_id,
                            agent_id=metadata.agent_id,
                            document_id=metadata.document_id,
                            chunk_index=chunk_index,
                            chunking_strategy="keyword",
                            timestamp=metadata.timestamp,
                            version=metadata.version,
                            parent_text=metadata.parent_text,
                        ),
                    )
                )
                chunk_index += 1
        return chunks
