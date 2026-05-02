# ADR-011: Qdrant Vector Store Backend

## Status
Accepted

## Context
TrueRAG supports pluggable vector stores through the `VectorStore` interface. We need a production-grade backend option optimized for vector search workloads and compatible with namespace isolation requirements.

## Decision
- Add `QdrantVectorStore` as a concrete `VectorStore` backend.
- Use Qdrant Cloud as the managed runtime.
- Use one Qdrant collection per namespace (`{tenant_id}_{agent_id}`).
- Use async `qdrant-client` (`AsyncQdrantClient`) for non-blocking operations.
- Resolve Qdrant API key through AWS Secrets Manager via `app.utils.secrets.get_secret`.
- Persist `namespace` in each point payload and verify it during query result mapping; raise `NamespaceViolationError` on mismatch.

## Consequences
- Operators can select `qdrant` backend per agent through existing provider registry.
- Namespace isolation remains enforced at provider read path as required by project guardrails.
- Adds dependency on `qdrant-client` and Qdrant service availability.
