from __future__ import annotations

import re
from typing import Any

import tiktoken

from app.interfaces.chunking_strategy import ChunkingStrategy
from app.models.chunk import Chunk, ChunkMetadata


class SemanticChunker(ChunkingStrategy):
    def __init__(
        self,
        similarity_threshold: float = 0.75,
        max_chunk_tokens: int = 512,
        **kwargs: Any,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.max_chunk_tokens = kwargs.get("chunk_size", max_chunk_tokens)
        self._enc = tiktoken.get_encoding("cl100k_base")
        self._nlp = self._load_spacy_pipeline()
        self._encoder = self._load_sentence_encoder()

    def _load_spacy_pipeline(self) -> Any:
        import spacy

        try:
            return spacy.load("en_core_web_sm")
        except OSError:
            nlp = spacy.blank("en")
            nlp.add_pipe("sentencizer")
            return nlp

    def _load_sentence_encoder(self) -> Any:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer("all-MiniLM-L6-v2")

    def _split_sentences(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        doc = self._nlp(text)
        sentences = [sent.text.strip() for sent in doc.sents if sent.text and sent.text.strip()]
        if sentences:
            return sentences
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    def _append_chunk_with_max_tokens(
        self, output_chunks: list[str], chunk_text: str, max_chunk_tokens: int
    ) -> None:
        tokens = self._enc.encode(chunk_text)
        if len(tokens) <= max_chunk_tokens:
            output_chunks.append(chunk_text)
            return
        for start in range(0, len(tokens), max_chunk_tokens):
            window = tokens[start : start + max_chunk_tokens]
            output_chunks.append(self._enc.decode(window))

    def chunk(self, text: str, metadata: ChunkMetadata) -> list[Chunk]:
        sentences = self._split_sentences(text)
        if not sentences:
            return []
        if len(sentences) == 1:
            return [
                Chunk(
                    text=sentences[0],
                    metadata=ChunkMetadata(
                        tenant_id=metadata.tenant_id,
                        agent_id=metadata.agent_id,
                        document_id=metadata.document_id,
                        chunk_index=0,
                        chunking_strategy="semantic",
                        timestamp=metadata.timestamp,
                        version=metadata.version,
                        parent_text=metadata.parent_text,
                    ),
                )
            ]

        embeddings = self._encoder.encode(sentences)
        merged_texts: list[str] = []
        current_group: list[str] = [sentences[0]]

        for idx in range(1, len(sentences)):
            similarity = self._cosine_similarity(embeddings[idx - 1], embeddings[idx])
            if similarity < self.similarity_threshold:
                merged_texts.append(" ".join(current_group))
                current_group = [sentences[idx]]
            else:
                current_group.append(sentences[idx])
        merged_texts.append(" ".join(current_group))

        token_limited_chunks: list[str] = []
        for merged in merged_texts:
            self._append_chunk_with_max_tokens(
                token_limited_chunks, merged, self.max_chunk_tokens
            )

        chunks: list[Chunk] = []
        for i, chunk_text in enumerate(token_limited_chunks):
            chunks.append(
                Chunk(
                    text=chunk_text,
                    metadata=ChunkMetadata(
                        tenant_id=metadata.tenant_id,
                        agent_id=metadata.agent_id,
                        document_id=metadata.document_id,
                        chunk_index=i,
                        chunking_strategy="semantic",
                        timestamp=metadata.timestamp,
                        version=metadata.version,
                        parent_text=metadata.parent_text,
                    ),
                )
            )
        return chunks
