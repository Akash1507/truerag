# ADR-012: Pinecone Vector Store Backend

## Status
Accepted

## Context
TrueRAG requires multiple vector store backends behind the `VectorStore` interface. Pinecone provides a managed, serverless vector database option for teams that want to avoid operating vector infrastructure directly.

## Decision
- Add `PineconeVectorStore` implementing the `VectorStore` interface.
- Use a shared Pinecone index (`truerag`) and native Pinecone namespaces for tenant-agent isolation.
- Pass `namespace` on all upsert, query, and delete operations.
- Resolve Pinecone API key from AWS Secrets Manager via `app.utils.secrets.get_secret`.
- Store `namespace` in vector metadata and verify query results return only the requested namespace.
- Run Pinecone SDK calls in a thread (`asyncio.to_thread`) to avoid blocking the async event loop.

## Consequences
- Tenant developers can choose `pinecone` per agent through existing provider registration.
- Namespace isolation semantics stay aligned with pgvector and Qdrant.
- Adds runtime dependency on Pinecone service and SDK availability.
