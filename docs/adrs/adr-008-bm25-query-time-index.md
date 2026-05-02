# ADR-008: BM25 Query-Time Index for Sparse Retrieval

- Status: Accepted
- Date: 2026-05-02
- Story: 7-2 Sparse Retrieval and Hybrid Search

## Context

We need sparse retrieval (`retrieval_mode: sparse`) and hybrid retrieval (`retrieval_mode: hybrid`) using BM25 + dense + RRF.  
Current architecture has only a vector store interface (`query`) and no separate search infrastructure for inverted indexes.

## Decision

For MVP, BM25 index is built at query time from chunk texts fetched from the agent namespace in vector storage.  
Implementation uses `rank-bm25` (`BM25Okapi`) in-process, with no persistent BM25 index store.

## Options Considered

1. Query-time BM25 index from vector store chunks (chosen)
- Pros: no new infrastructure, minimal operational complexity, faster delivery.
- Cons: O(N) scoring and corpus fetch per query; higher latency as corpus grows.

2. Persistent BM25 index in a separate service/store (not chosen)
- Pros: lower per-query cost for large corpora.
- Cons: additional infra, consistency/sync complexity, index lifecycle management.

## Consequences

- Sparse retrieval is available now with predictable behavior.
- Hybrid retrieval can run dense and sparse in parallel and fuse results via RRF.
- Performance tradeoff is explicit: query-time corpus fetch and BM25 scoring add latency proportional to corpus size.
- This is acceptable for MVP-scale corpora; SLA comparison against dense-only remains a measurement concern in ongoing perf validation.

## Follow-up

- Add corpus-size guardrails and retrieval telemetry dashboards.
- Revisit persistent sparse index architecture if p95 latency regresses beyond target at scale.
