# ADR 009: Reranking with Cross-Encoder and Cohere

**Status:** Accepted  
**Date:** 2026-05-02  
**Story:** 7.3

---

## Context

Retrieval order from vector or sparse search does not always match semantic relevance for final answer generation. We need a configurable reranking stage that supports both local inference and managed API-based reranking, while preserving the locked synchronous `Reranker.rerank()` interface.

---

## Decision

1. Use the retrieve-wide-rerank-narrow pattern.
`rerank_pool_size` is added to agent config (default `20`, bounds `1..200`). Retrieval fetches `max(top_k, rerank_pool_size)` when reranking is enabled, and `top_k` when reranker is `none`.

2. Add local cross-encoder reranker.
`CrossEncoderReranker` uses `sentence-transformers` with model `cross-encoder/ms-marco-MiniLM-L-6-v2`, loaded once in `__init__`. It scores `(query, chunk)` pairs synchronously and returns top results by descending relevance.

3. Add Cohere reranker.
`CohereReranker` uses model `rerank-english-v3.0` through `cohere` SDK. API key is read from AWS Secrets Manager via `app.utils.secrets.get_secret("cohere/api_key")`. API invocation is wrapped with `@retry` for transient failures.

4. Keep reranker contract synchronous.
The pipeline and rerankers keep the existing sync interface; no async signature changes are introduced to `Reranker`.

---

## Consequences

- Tenant developers can switch `reranker` by config only (`none`, `cross_encoder`, `cohere`) with no pipeline shape changes.
- Reranking improves relevance quality while maintaining control of latency via bounded pool size.
- Cohere secret management remains centralized through existing secrets utilities.

---

## References

- `_bmad-output/planning-artifacts/architecture.md` (FR25, interface constraints)
- `_bmad-output/implementation-artifacts/7-3-reranking-local-cross-encoder-and-cohere-rerank.md`
