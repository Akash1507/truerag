# TrueRAG — Requirements Brief

**Project:** TrueRAG  
**Author:** Akash  
**Blog/Channel:** buildbeyondbackend.com  
**Date:** April 2026

---

## What Are We Building

TrueRAG is a production-grade open-source RAG Engine. It is the retrieval primitive of a larger AI platform called TruePlatform. It is fully functional as a standalone service and simultaneously designed to be consumed by orchestration layers.

The core idea: instead of building bespoke RAG pipelines per use case, teams register named RAG Agents through an API — each a fully configured retrieval pipeline with its own isolated knowledge base. No code changes to switch strategies, models, or providers. Everything is configuration.

---

## Who Uses It

**Tenant Developer** — registers RAG Agents, uploads documents, configures retrieval strategy via API. No code written.

**Service Consumer** — queries a RAG Agent via REST API. Receives grounded answers with citations and confidence scores.

**Platform Admin** — monitors cost, latency, and eval scores across all tenants and agents.

**AI Platform Engineer** — deploys, maintains, and extends TrueRAG as part of TruePlatform.

---

## Core Abstractions

### Tenant
A team or organisation using TrueRAG. Groups RAG Agents for cost attribution and access control.

### RAG Agent
The primary unit. A named, fully configured retrieval pipeline. Each agent has its own isolated knowledge base, its own strategy configuration, and its own evaluation dataset. A tenant can have unlimited RAG Agents.

Example:
```
Tenant: Legal Team
├── RAG Agent: contract-analyser      (one config)
└── RAG Agent: case-law-researcher    (different config)
```

### Dynamic Configuration
All tenant and agent configuration is stored in MongoDB — not flat files, not environment variables. This gives the system dynamic nature — configs can be created, updated, and read at runtime without restarts or deployments. The system reads agent config from MongoDB on every relevant operation.

### Namespace Isolation
Every RAG Agent gets its own isolated namespace in the vector store. Isolation is enforced at the vector store query level — not the application layer. One agent cannot reach another agent's documents under any circumstance.

---

## What The System Must Do

### Tenant Management
- Register a new tenant
- Delete a tenant and everything associated with it
- List all tenants
- Tenant metadata stored in MongoDB

### RAG Agent Management
- Create a named RAG Agent under a tenant with full configuration
- Update agent configuration at runtime — changes take effect without restart
- Delete an agent and its isolated namespace
- List all agents for a tenant
- Get agent config and current status
- Agent configuration stored in MongoDB — dynamic, not static files

### Document Ingestion
- Accept PDF, TXT, Markdown, DOCX
- Ingestion is asynchronous — upload returns immediately, processing in background
- Provide status polling so caller knows when processing is complete
- Scrub PII from document content before any chunk enters the vector store
- Archive raw documents to object storage before processing
- Support document versioning — re-ingesting creates a new version, old version archived
- Support document deletion — removes all chunks from the agent namespace
- Every chunk carries metadata: tenant, agent, document, chunk index, strategy used, timestamp, version

### Chunking
Four strategies, all selectable per agent:
- **Fixed-size** — split by token count with configurable size and overlap
- **Semantic** — split on meaning boundaries, respecting semantic units
- **Hierarchical** — small chunks for retrieval, larger parent chunks for context
- **Document-aware** — respect document structure: headings, sections, tables

New chunking strategies must be addable without modifying core ingestion logic.

### Embedding
- Support multiple embedding providers: OpenAI, Cohere, AWS Bedrock
- Embedding model configurable per agent via MongoDB config
- When agent changes embedding model, existing chunks are re-embedded

### Vector Store
- Support three backends: pgvector, Qdrant, Pinecone
- All three accessed through a single abstract interface
- Active backend switchable via config — zero code change
- Each RAG Agent has its own isolated namespace in the vector store
- New backends must be addable without modifying retrieval logic

### Retrieval
Three modes, selectable per agent:
- **Dense** — vector similarity search
- **Sparse** — BM25 keyword search
- **Hybrid** — dense and sparse run in parallel, merged via Reciprocal Rank Fusion

Additional retrieval requirements:
- Metadata filtering — scope retrieval by document tags, date, category
- Configurable top-k per agent
- All retrieval hard-filtered by agent namespace

### Reranking
- Support local cross-encoder reranker — free, no external API
- Support Cohere Rerank API — managed, higher quality
- Support disabling reranking entirely
- Selectable per agent
- Pattern: retrieve wider pool, rerank to final top-k
- New rerankers must be addable without modifying retrieval logic

### Query Processing
- Optional query rewriting — expand query for better recall
- Query routing — determine if retrieval is needed or LLM can answer directly
- Confidence scoring on retrieved chunks

### Generation
- Config-driven LLM providers: OpenAI, Anthropic, AWS Bedrock
- LLM provider and model configurable per agent via MongoDB config
- Inject retrieved chunks as context into the prompt
- Return citations with every answer — which chunks contributed, from which document
- Return confidence score on every generated answer
- Support structured JSON output when requested

### Semantic Caching
- Cache responses by semantic similarity of the query
- Cache scoped per RAG Agent namespace
- Cache hits logged and included in metrics
- Configurable similarity threshold
- Cache invalidated when agent documents are updated

### Evaluation
- Support golden dataset per agent — curated question/answer pairs stored in MongoDB
- Compute RAGAS scores: faithfulness, answer relevance, context recall, context precision
- Store every experiment result — config combination and scores — in MongoDB
- Detect regressions — flag when scores drop below agent baseline
- Eval triggerable manually via API and automatically via CI-CD pipeline

### Observability
- Structured JSON logging for every ingestion step and retrieval step
- Every log entry includes: tenant ID, agent ID, operation, latency, timestamp
- Track latency per pipeline stage: chunking, embedding, retrieval, reranking, generation
- Track cost per query: tokens used, embedding calls, reranker API calls
- Metrics endpoint for monitoring integration
- Health and readiness endpoints

---

## What It Must Not Do

- Must not allow one agent's query to reach another agent's documents
- Must not allow PII to reach the vector store or LLM
- Must not block retrieval while ingestion is running
- Must not require code changes or restarts to update agent configuration
- Must not require code changes to switch LLM provider, embedding model, or vector store backend
- Must not store secrets in code or configuration files

---

## Extension Points

Three things must be extensible by implementing an interface and registering in config, with no changes to core logic:

1. **Vector Store backends** — add Weaviate, Chroma, OpenSearch
2. **Chunking strategies** — add Graph RAG chunking, sliding window, domain-specific
3. **Rerankers** — add BGE reranker, Voyage reranker, custom cross-encoders

---

## Out Of Scope For v1

- Graph RAG retrieval
- Multi-modal ingestion (images, audio, video)
- Model fine-tuning or training
- Frontend UI — API only
- Streaming responses
- Real-time document sync from Confluence, Notion, SharePoint
- Hard infrastructure isolation per tenant (namespace isolation is sufficient for internal platform)

---

## Platform Integration Context

TrueRAG is built as a standalone service that is simultaneously platform-ready. It will eventually be consumed by TrueGateway and a LangGraph orchestration layer as part of TruePlatform. Design decisions should ensure clean integration without requiring changes to TrueRAG when the platform layer is built.

---

## Build Approach

- Python only
- API-first — everything accessible via REST
- Config-driven — all provider, strategy, and model choices via MongoDB-stored config
- Built stage by stage, each stage independently demonstrable
- Deployed on real AWS infrastructure
- Every architectural decision documented as an ADR in the repository
- Built in public — YouTube series on buildbeyondbackend.com
