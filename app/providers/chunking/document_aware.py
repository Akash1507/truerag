from __future__ import annotations

import re
from typing import Any

import tiktoken

from app.interfaces.chunking_strategy import ChunkingStrategy
from app.models.chunk import Chunk, ChunkMetadata

_HEADING_RE = re.compile(r"^#{1,6}\s+.+")
_DIVIDER_RE = re.compile(r"^(-{3,}|={3,}|\*{3,})$")


class DocumentAwareChunker(ChunkingStrategy):
    def __init__(self, max_chunk_tokens: int = 512, **kwargs: Any) -> None:
        self.max_chunk_tokens = kwargs.get("chunk_size", max_chunk_tokens)
        self._enc = tiktoken.get_encoding("cl100k_base")

    @staticmethod
    def _is_table_line(line: str) -> bool:
        return line.strip().startswith("|")

    @staticmethod
    def _is_structural_boundary(line: str) -> bool:
        stripped = line.strip()
        return bool(_HEADING_RE.match(stripped) or _DIVIDER_RE.match(stripped))

    def _split_structural_sections(self, text: str) -> list[str]:
        lines = text.splitlines()
        if not lines:
            return []
        sections: list[str] = []
        current: list[str] = []
        in_table = False

        for line in lines:
            is_table = self._is_table_line(line)
            if is_table:
                if not in_table and current:
                    sections.append("\n".join(current).strip())
                    current = []
                in_table = True
                current.append(line)
                continue

            if in_table:
                sections.append("\n".join(current).strip())
                current = []
                in_table = False

            if self._is_structural_boundary(line):
                if current:
                    sections.append("\n".join(current).strip())
                    current = []
                current.append(line)
                continue

            current.append(line)

        if current:
            sections.append("\n".join(current).strip())

        return [section for section in sections if section]

    def _subchunk_if_needed(self, section_text: str) -> list[str]:
        tokens = self._enc.encode(section_text)
        if len(tokens) <= self.max_chunk_tokens:
            return [section_text]
        output: list[str] = []
        for start in range(0, len(tokens), self.max_chunk_tokens):
            output.append(self._enc.decode(tokens[start : start + self.max_chunk_tokens]))
        return output

    def chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]:
        if not text or not text.strip():
            return []
        sections = self._split_structural_sections(text)
        chunk_texts: list[str] = []
        for section in sections:
            chunk_texts.extend(self._subchunk_if_needed(section))

        chunks: list[Chunk] = []
        for i, chunk_text in enumerate(chunk_texts):
            chunks.append(
                Chunk(
                    text=chunk_text,
                    metadata=ChunkMetadata(
                        tenant_id=metadata.tenant_id,
                        agent_id=metadata.agent_id,
                        document_id=metadata.document_id,
                        chunk_index=i,
                        chunking_strategy="document_aware",
                        timestamp=metadata.timestamp,
                        version=metadata.version,
                        parent_text=metadata.parent_text,
                    ),
                )
            )
        return chunks
