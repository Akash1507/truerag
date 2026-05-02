# ADR-007: Semantic, Hierarchical, and Document-Aware Chunking Strategy

## Status
Accepted

## Context
Epic 7 requires advanced chunking strategies beyond fixed-size token windows to improve retrieval quality:
- semantic boundary aware chunking
- hierarchical parent-child chunking
- document-structure aware chunking

These strategies must plug into the existing `CHUNKING_REGISTRY` and keep ingestion pipeline/service interfaces unchanged.

## Decision
1. Semantic strategy
- Use spaCy sentence segmentation as the sentence boundary detector.
- Use `sentence-transformers` embeddings (`all-MiniLM-L6-v2`) per sentence.
- Greedily merge adjacent sentences while cosine similarity stays above threshold (default `0.75`).
- Enforce max chunk token size using `tiktoken` (`cl100k_base`).

2. Hierarchical strategy
- First split into large parent windows (default `1024` tokens).
- Split each parent into smaller child windows (default `256` tokens, overlap `25`).
- Store the decoded parent text directly on `ChunkMetadata.parent_text`.
- Chosen storage approach: embed `parent_text` in chunk metadata (no new parent store required).

3. Document-aware strategy
- Detect structure using line-based regexes:
  - Markdown headings: `^#{1,6}\s+.+`
  - Dividers/horizontal rules: `^(-{3,}|={3,}|\*{3,})$`
  - Table lines: `|...`
- Split by structural sections and avoid table row splits.
- For oversized sections, subchunk within section by fixed token windows.

## Consequences
- Better retrieval units aligned to meaning and document structure.
- Higher ingestion CPU cost and latency, especially semantic chunking.
- `sentence-transformers` model loading increases runtime/dependency footprint.
- No pipeline API changes required; construction stays registry-driven.

## Limitations
- Semantic chunking is CPU-bound and slower than fixed-size.
- Similarity-threshold heuristics can over/under-split depending on domain text.
- Document-aware regex detection is intentionally lightweight and may miss complex nested structures.
