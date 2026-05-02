# ADR-013: Cohere and AWS Bedrock Embedding Providers

## Status
Accepted

## Context
TrueRAG supports pluggable embedding providers and must avoid serving degraded retrieval results when an agent switches embedding providers after vectors are already indexed.

## Decision
- Add `CohereEmbedder` and `BedrockEmbedder` implementations behind `EmbeddingProvider`.
- Register both providers in `EMBEDDING_REGISTRY` for config-driven provider selection.
- Add persisted `embedding_provider_mismatch` flag on `AgentDocument`.
- Set `embedding_provider_mismatch=True` when `embedding_provider` changes while existing documents are present.
- Block query execution with `EmbeddingModelMismatchError` (HTTP 422) when mismatch flag is true.
- Reset mismatch flag to `False` when developer-triggered full reindex is enqueued successfully.

## Consequences
- Multi-provider embedding selection is available without code changes.
- Query-time safety prevents silent quality degradation from mixed embedding spaces.
- Reindex becomes mandatory after provider switch when historical vectors exist.
