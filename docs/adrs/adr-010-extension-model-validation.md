# ADR-010: Extension Model Validation via Abstract Interfaces and Registries

## Status
Accepted

## Date
2026-05-02

## Context
The platform architecture defines five provider-facing abstract interfaces:
- `ChunkingStrategy`
- `Reranker`
- `VectorStore`
- `EmbeddingProvider`
- `LLMProvider`

Providers are selected by string configuration on agents and resolved through registry maps in `app/providers/registry.py`. Epic 7 introduced multiple new provider implementations and required proving that the extension model works without touching pipeline, service, or API orchestration.

## Decision
We validate extension through a concrete proof-of-concept provider and strict contract enforcement:

1. New backend integration follows exactly three steps:
- Implement the relevant abstract interface in `app/providers/{category}/`.
- Register the class in the corresponding registry in `app/providers/registry.py`.
- Add its config key to the appropriate `VALID_*` set in `app/models/agent.py`.

2. `KeywordChunker` is introduced as a minimal `ChunkingStrategy` backend proving this path. It splits by paragraph boundaries with token-cap fallback and is registered as `"keyword"`.

3. Contract enforcement is performed with `mypy --strict app/interfaces/ app/providers/` and provider-agnostic contract tests for chunking, reranking, and vector stores.

## Consequences
Positive:
- Confirms backend extensibility without core orchestration changes.
- Enforces interface compliance at static-analysis time.
- Adds regression protection using backend-agnostic contract suites.

Tradeoffs:
- Strict typing increases upfront implementation effort for new providers.
- Contract tests require explicit provider registration parity over time.
