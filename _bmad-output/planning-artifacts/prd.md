---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-02b-vision
  - step-02c-executive-summary
  - step-03-success
  - step-04-journeys
  - step-05-domain
  - step-06-innovation
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
  - step-12-complete
classification:
  projectType: api_backend
  domain: scientific
  complexity: medium
  projectContext: brownfield
inputDocuments:
  - _bmad-output/project-context.md
  - _bmad-output/planning-artifacts/requirements-brief.md
workflowType: 'prd'
---

# Product Requirements Document - truerag

**Author:** Akash
**Date:** 2026-04-17

## Executive Summary

TrueRAG is a production-grade open-source RAG Engine — the retrieval primitive of TruePlatform. It solves a specific organisational problem: teams inside a company independently build the same RAG pipelines from scratch, accumulating the same chunking mistakes, the same retrieval bugs, the same absence of evaluation, and the same cost visibility gap. Platform engineers watch this replication happen with no governance and no shared layer to offer instead.

TrueRAG replaces bespoke pipeline sprawl with a governed, config-driven retrieval service. Teams register named RAG Agents via API — each a fully isolated, fully configured retrieval pipeline. No code is written to change a chunking strategy, swap a vector store backend, or switch an LLM provider. Everything is configuration, stored in MongoDB, readable and writable at runtime. The retrieval pipeline becomes infrastructure, not implementation.

**Target users:** Tenant Developers who register agents and upload documents; Service Consumers who query agents via REST and receive grounded answers with citations and confidence scores; Platform Admins who govern cost, latency, and quality across tenants; AI Platform Engineers who deploy and extend TrueRAG within TruePlatform.

**Why now:** RAG has crossed from experimental to production-critical. Companies are no longer asking whether to use RAG — they are asking why their RAG is inconsistent, unmeasured, and expensive. The open-source tooling gap is real: tutorials on one end, enterprise black-boxes on the other. TrueRAG fills the middle: production-grade, open-source, designed as a platform primitive for engineers who think in systems.

### What Makes This Special

The differentiator is runtime reconfigurability with zero code change. A developer registers a RAG Agent with hierarchical chunking and pgvector, queries it, sees citations and confidence scores. Then updates two config fields — switches to hybrid search and Qdrant — and queries again. No code changed. No redeployment. The agent config updated in MongoDB and the next query used the new strategy. That moment — measurably different results from a config change — demonstrates that the retrieval pipeline is a governed infrastructure layer, not a codebase artifact.

Three extension points enforce the platform primitive design: VectorStore, ChunkingStrategy, and Reranker are abstract interfaces. New backends are registered in config, not wired into core logic. This ensures TrueRAG remains extensible without becoming fragile.

**Built in public** on buildbeyondbackend.com, targeting mid-to-senior backend engineers being pulled into AI systems work. Every architectural decision ships as an ADR. The code is the tutorial.

**Classification:** API Backend (multi-tenant platform) · AI/ML Infrastructure · Medium complexity · Brownfield

## Success Criteria

### User Success

- A Tenant Developer registers a RAG Agent, uploads a PDF, and receives a grounded answer with citations and a confidence score — without writing a single line of code
- Config changes (chunking strategy, vector store backend, LLM provider) take effect on the next query with no code change and no redeployment
- A 10-page PDF is fully processed and queryable within 60 seconds of upload
- Status polling gives the caller accurate visibility into ingestion progress at every stage

### Business Success

- All 12 build stages complete and independently demonstrable on real AWS infrastructure
- YouTube series on buildbeyondbackend.com documents the full build end-to-end
- v1 success is purely technical correctness — GitHub stars and community growth are v2 concerns

### Technical Success

- **Query latency:** p95 end-to-end (retrieval + reranking + generation) under 3 seconds; p95 without reranking under 1.5 seconds
- **Namespace isolation:** Zero tolerance — any cross-namespace result is a critical failure, not a warning or degraded state
- **Ingestion throughput:** A 10-page PDF fully processed and queryable within 60 seconds of upload
- **RAGAS faithfulness:** Baseline acceptable above 0.7; below 0.6 triggers an automatic regression flag
- **PII scrubbing:** Zero PII reaches the vector store or LLM — enforced pre-chunk, not post-retrieval
- **Async isolation:** Ingestion never blocks the retrieval path under any load condition

### Measurable Outcomes

| Metric | Target | Failure Threshold |
|---|---|---|
| Query p95 latency (with reranking) | < 3s | > 5s |
| Query p95 latency (without reranking) | < 1.5s | > 3s |
| Ingestion time (10-page PDF) | < 60s | > 120s |
| RAGAS faithfulness | > 0.7 | < 0.6 (auto-flag) |
| Cross-namespace isolation violations | 0 | Any = critical failure |
| PII in vector store or LLM context | 0 | Any = critical failure |

## Product Scope

### MVP — Minimum Viable Product

One of everything, working end-to-end on real AWS infrastructure:

- Tenant and RAG Agent management with MongoDB-stored config
- Async ingestion — PDF and TXT, fixed-size chunking, PII scrubbing, S3 archive
- pgvector as the single vector store backend
- Dense retrieval only
- OpenAI as the single embedding provider
- Anthropic as the single LLM provider
- Citations and confidence scores on every response
- Basic RAGAS evaluation (faithfulness, answer relevance, context recall, context precision)
- Structured JSON logging with tenant ID, agent ID, operation, latency, timestamp
- Health and readiness endpoints

### Growth Features (Post-MVP)

Everything else in the requirements brief:

- All four chunking strategies (semantic, hierarchical, document-aware)
- Hybrid search (dense + sparse via BM25, merged via RRF) and reranking (local cross-encoder + Cohere Rerank)
- All three vector stores behind the abstract VectorStore interface (Qdrant, Pinecone)
- All embedding providers (Cohere, AWS Bedrock) and LLM providers (OpenAI, AWS Bedrock)
- Semantic caching scoped per agent namespace
- Document versioning and deletion
- Full observability: per-stage latency tracking, cost-per-query (tokens, embedding calls, reranker calls), metrics endpoint
- Evaluation regression detection and CI-CD pipeline integration

### Vision (Future)

- Graph RAG retrieval
- Multi-modal ingestion (images, audio, video)
- Streaming responses
- Real-time document sync (Confluence, Notion, SharePoint)
- TrueGateway and LangGraph orchestration layer integration (TruePlatform)

## User Journeys

### Journey 1: The Tenant Developer — First Agent to First Answer

**Persona:** Priya is a backend engineer at a legal tech startup. Her team has been asked to add contract analysis to their product. She's been told to "use RAG." She's read the tutorials. She doesn't want to build a bespoke pipeline — she wants something she can govern, extend, and hand over.

**Opening Scene:** Priya has TrueRAG deployed. She opens the API docs. She has a collection of contract PDFs and a clear question: can she get reliable, cited answers from them without writing retrieval logic?

**Rising Action:** She calls `POST /tenants` to register her team. She calls `POST /agents` with a config block — agent name `contract-analyser`, fixed-size chunking, pgvector, OpenAI embeddings, Anthropic generation, dense retrieval. One API call. No code. She uploads three PDFs via `POST /agents/contract-analyser/documents`. She polls the ingestion status endpoint. Within 45 seconds, status is `ready`.

**Climax:** She sends her first query: *"What are the termination clauses in the uploaded contracts?"* The response comes back in 1.8 seconds. It includes a direct answer, three cited chunks with document names and page references, and a confidence score of 0.84. She pastes one citation into the source document to verify. It's accurate.

**Resolution:** Priya registers a second agent — `case-law-researcher` — with a different config. Two agents, two isolated knowledge bases, one platform. She didn't write retrieval logic. She didn't manage vector store namespaces manually. She presents the working prototype to her team the same afternoon.

**Requirements revealed:** Tenant registration API, agent creation with full config, async document ingestion with status polling, dense retrieval, citations with document + chunk reference, confidence scoring, namespace isolation between agents.

---

### Journey 2: The Tenant Developer — Config Swap (The Differentiator Moment)

**Persona:** Same Priya, two weeks later. The contract-analyser agent is in staging. Answer quality is acceptable but not great — she suspects the chunking strategy isn't preserving clause boundaries well.

**Opening Scene:** She checks the RAGAS eval scores for the agent. Faithfulness is 0.71 — above threshold but barely. She wants to test hierarchical chunking, which preserves larger parent context.

**Rising Action:** She calls `PATCH /agents/contract-analyser/config` — changes `chunking_strategy` from `fixed_size` to `hierarchical`. The API confirms the update and returns a warning: *"Chunking strategy updated. Existing chunks were generated with `fixed_size`. Re-ingestion required for changes to take effect."* The system does not re-ingest automatically — Priya explicitly calls `POST /agents/contract-analyser/reindex` to trigger it. She runs the same eval queries once reindexing completes.

**Climax:** Faithfulness jumps to 0.83. Answer relevance improves. No code change. No redeployment. The pipeline read the updated config from MongoDB on the next operation. The re-ingestion was a deliberate developer action — not a silent side effect.

**Resolution:** Priya updates the agent config in production the same way. She now understands TrueRAG's core promise: the retrieval pipeline is configuration, not code. She files a note in the team wiki: *"To change retrieval behaviour, edit the agent config. Trigger reindex if chunking strategy changes. Do not touch the codebase."*

**Requirements revealed:** Runtime config update API, chunking strategy mismatch detection with explicit warning, developer-triggered reindex endpoint, RAGAS eval per agent, regression comparison between eval runs.

---

### Journey 3: The Service Consumer — Querying Under the Hood

**Persona:** Dev is a product engineer. He doesn't know or care what's inside TrueRAG. His job is to integrate a contract Q&A feature into a customer-facing product. He consumes the RAG Agent via REST.

**Opening Scene:** Dev has the agent ID and base URL. He needs to integrate query responses into a UI that shows answers with source references. He needs predictable response structure, reliable latency, and citations he can render as footnotes.

**Rising Action:** He sends `POST /agents/contract-analyser/query` with a natural language question. He inspects the response schema — `answer`, `confidence`, `citations[]` (each with `document_name`, `chunk_text`, `page_reference`), `latency_ms`. The structure is consistent across queries.

**Climax:** He builds the UI integration in an afternoon. Citations render as collapsible footnotes. Confidence score drives a visual indicator. p95 latency stays under 2 seconds in load testing — within the UI's acceptable response budget.

**Resolution:** The feature ships. Dev never touched the RAG configuration. He never knew which vector store or chunking strategy was active. He consumed retrieval as an API — exactly as intended.

**Requirements revealed:** Consistent query response schema, citations array with document + chunk metadata, confidence score on every response, structured JSON output, predictable p95 latency.

---

### Journey 4: The Platform Admin — Cost and Quality Governance

**Persona:** Rania is a platform engineer responsible for TruePlatform's infrastructure costs and quality SLAs. She didn't build TrueRAG — she governs it. She needs visibility into which agents are expensive, which are underperforming, and which teams are causing cost spikes.

**Opening Scene:** It's end of month. Rania receives a pushed regression alert: *"Agent `contract-analyser` (Tenant: Legal Team) — RAGAS faithfulness dropped from 0.78 to 0.54. Threshold: 0.60. Triggered: 2026-04-14T09:23:11Z."* She didn't poll for it. TrueRAG pushed the alert when the score crossed the regression threshold.

**Rising Action:** She opens the metrics endpoint to investigate. Per-agent breakdown shows token usage, embedding API calls, reranker API calls, query volume, and average latency for `contract-analyser`. The faithfulness drop correlates with a document re-ingestion batch added three days ago. She checks the structured logs — the batch contained poorly formatted PDFs flagged during PII scrubbing with low-confidence passes.

**Climax:** She also notices a separate agent with a cost-per-query 4x higher than others. Its config shows top-k set to 50, Cohere Rerank active, and GPT-4 as the LLM provider. She flags it to the owning team.

**Resolution:** Rania has governance across the platform — cost, latency, quality — without accessing any team's document content. Both issues are traceable to specific agents, specific operations, and specific timestamps. She files a cost optimisation recommendation and a data quality issue within the same session.

**Requirements revealed:** Push-based RAGAS regression alerts (threshold breach triggers notification, not poll), metrics endpoint with per-tenant/per-agent breakdown, cost-per-query tracking (tokens + embedding + reranker calls), eval history per agent, structured logs queryable by tenant and agent.

---

### Journey 5: The AI Platform Engineer — Extending TrueRAG

**Persona:** Tariq is the engineer who owns TrueRAG as part of TruePlatform. A team has asked for Weaviate as a vector store backend — it's not in the current implementation. He needs to add it without touching core retrieval logic.

**Opening Scene:** Tariq opens the VectorStore abstract interface. It defines `upsert`, `query`, `delete_namespace`, and `health`. He needs to implement these for Weaviate.

**Rising Action:** He creates a `WeaviateVectorStore` class implementing the interface. He registers it in the provider config. He writes a test agent that points to the new backend. He updates the agent config — `vector_store: weaviate` — and runs the standard retrieval test suite.

**Climax:** The test suite passes. The Weaviate backend behaves identically to pgvector and Qdrant from the retrieval path's perspective. Core retrieval logic was never touched. He opens a PR with the new class and an ADR documenting the integration decision.

**Resolution:** The requesting team updates their agent config to `vector_store: weaviate`. No deployment change. No core logic modification. Tariq merges the PR and documents the extension point in the repo.

**Requirements revealed:** Abstract VectorStore interface with defined contract, provider registration in config, extension without core modification, ADR documentation standard.

---

### Journey Requirements Summary

| Journey | Key Capabilities Required |
|---|---|
| Tenant Developer — First Agent | Tenant/agent management API, async ingestion, status polling, dense retrieval, citations, confidence scores, namespace isolation |
| Tenant Developer — Config Swap | Runtime config update, chunking strategy mismatch warning, developer-triggered reindex, RAGAS eval, regression comparison |
| Service Consumer | Consistent query schema, citations array, confidence score, structured JSON, p95 latency guarantee |
| Platform Admin | Push-based RAGAS regression alerts, metrics endpoint, cost-per-query tracking, eval history, per-tenant/agent structured logs |
| AI Platform Engineer | Abstract VectorStore interface, provider config registration, extension without core modification, ADR standard |

## Domain-Specific Requirements

### Security & Access Control

- **API key authentication:** Every tenant receives an API key on registration, stored in MongoDB. All requests pass the key as a header. TrueRAG validates the key, resolves the tenant, and rejects any request with an invalid or missing key.
- **Tenant isolation at the API layer:** A tenant can only access their own agents. Cross-tenant access is rejected before any retrieval logic executes. JWT and OAuth are out of scope for v1.
- **Namespace isolation:** Enforced at the vector store query level — not application logic. One agent's query cannot reach another agent's documents under any condition.
- **Secrets management:** All credentials (LLM provider keys, embedding provider keys, vector store credentials) are read from AWS Secrets Manager on each operation — not cached at startup. Credential rotation takes effect on the next request with no restart required.

### Privacy & PII

- **PII scrubbing scope:** Applied to both ingested document content and incoming query text. A query containing names, addresses, or identifiable information has PII stripped before it reaches the retrieval pipeline or LLM.
- **Audit log privacy:** Full query text is never stored. The audit log records a query hash only — sufficient for debugging and correlation without exposing user input.
- **No PII in vector store or LLM context:** Enforced pre-chunk for documents, pre-retrieval for queries. Zero tolerance — same failure class as namespace isolation violations.

### Data & Infrastructure Constraints

- **Single-region deployment:** v1 deploys to AWS `us-east-1` by default. Multi-region and data residency configurability are v2 concerns.
- **Audit log storage:** DynamoDB, separate from operational logs. Not shared with the ingestion job status table.

### Audit Requirements

A lightweight, tamper-evident audit log is required for v1, separate from operational observability logs. Every query event records:

| Field | Value |
|---|---|
| `tenant_id` | Tenant identifier |
| `agent_id` | Agent identifier |
| `api_key_hash` | SHA-256 hash of the caller's API key — never the key itself |
| `query_hash` | Hash of the query text — never the query text itself |
| `timestamp` | ISO 8601 UTC |
| `response_confidence` | Confidence score returned to caller |
| `cache_hit` | Boolean — `true` if response served from semantic cache; `false` (default) for full retrieval |

The audit log does not store: query text, retrieved chunks, generated answer, or document content.

### Risk Mitigations

| Risk | Mitigation |
|---|---|
| Cross-namespace data leak | Namespace enforced at vector store query level; any violation is a critical failure |
| PII reaching vector store or LLM | Scrubbing applied pre-chunk and pre-query; not post-retrieval |
| Credential exposure | Secrets Manager only; no secrets in code, config files, or environment variables |
| Cross-tenant access | API key resolved to tenant at request boundary; rejected before any logic executes |
| Audit log tampering | Stored in DynamoDB separate from operational systems; query text never written |

## Innovation & Novel Patterns

### Detected Innovation Areas

**Runtime reconfigurability:** TrueRAG's core architectural innovation is a retrieval pipeline with zero-restart, zero-code-change reconfiguration. All strategy, provider, and model choices are stored in MongoDB and read at operation time. Changing chunking strategy, vector store backend, LLM provider, or retrieval mode requires updating one config document — the next request executes the new configuration. This is the differentiator moment described in Journey 2: measurably different results from a config change, with no deployment.

**RAG as a platform primitive:** TrueRAG reframes RAG from a pipeline pattern (build it yourself, per use case) to an infrastructure primitive (register an agent, consume via API). This is the core response to the standardisation problem: instead of five teams each building bespoke RAG pipelines, they register named RAG Agents and consume a governed retrieval service. Namespace isolation enforced at the vector store query level makes multi-tenancy safe by design, not by convention.

**Extensible interface trifecta:** Three abstract interfaces — `VectorStore`, `ChunkingStrategy`, `Reranker` — define TrueRAG's extension model. New backends are added by implementing the interface and registering in config. Core retrieval logic is never modified. This pattern makes TrueRAG genuinely open for extension without being open for modification — a rare property in AI tooling.

### Market Context & Competitive Landscape

The open-source RAG market in 2026 divides into three categories:

- **Tutorial libraries** (LangChain, LlamaIndex): Code-first, pipeline-per-use-case, no multi-tenancy, no governance, no eval integration
- **Enterprise black-boxes** (proprietary RAG platforms): Governed but not open, not extensible by design, not built for platform engineers
- **Frameworks** (Haystack, RAGFlow): Closer to TrueRAG, but not designed as multi-tenant platform primitives with runtime reconfigurability as a first principle

TrueRAG's gap: production-grade, open-source, API-first, multi-tenant, runtime-reconfigurable, with built-in eval. No direct equivalent exists.

### Validation Approach

| Innovation | Validation Method |
|---|---|
| Runtime reconfigurability | Journey 2 demo: change config, query, observe different results — no restart, no code change |
| RAG as platform primitive | Two tenants, multiple agents per tenant, prove namespace isolation under concurrent queries |
| Extensible interface trifecta | Add a new vector store backend (e.g., Weaviate) without modifying core retrieval — covered in Journey 5 |

### Risk Mitigation

| Innovation Risk | Mitigation |
|---|---|
| MongoDB config read on every operation adds latency | Connection pooling + request-scoped in-memory config cache (few-second TTL). Config read once per request across all pipeline stages, not once per stage. Cache is request-scoped — runtime updates take effect on the next request. |
| Abstract interface over three vector stores increases test surface | Backend-agnostic test suite — same assertions, swapped backend. Sequential validation (pgvector → Qdrant → Pinecone) ensures only one new backend is validated at a time. |

*Full technical risk table including ingestion failure handling and PII scrubbing risks: see Project Scoping & Phased Development.*

## API Backend Specific Requirements

### Project-Type Overview

TrueRAG is a REST API backend with multi-tenant platform characteristics. All functionality is exposed via HTTP endpoints — no CLI, no UI, no SDK in v1. The API is the product. FastAPI generates OpenAPI documentation automatically; this is the primary developer interface.

### Authentication & Authorization Model

- **Mechanism:** API key per tenant, passed as `X-API-Key` header on every request
- **Resolution:** TrueRAG validates the key against MongoDB on each request and resolves the tenant from it
- **Enforcement:** Cross-tenant access rejected at the API layer before any business logic executes
- **Storage:** API key stored in MongoDB; never logged, never returned after initial issuance
- **Audit:** API key hash (SHA-256) recorded in the audit log — never the raw key

### Endpoint Specification

All endpoints prefixed with `/v1/`. The `/v1/` prefix is required from day one to ensure future versioning is non-breaking for consumers. v1 APIs may change until the first stable release tag — documented explicitly in the README.

| Group | Endpoints |
|---|---|
| **Tenant Management** | `POST /v1/tenants`, `GET /v1/tenants`, `DELETE /v1/tenants/{tenant_id}` |
| **Agent Management** | `POST /v1/agents`, `GET /v1/agents`, `GET /v1/agents/{agent_id}`, `PATCH /v1/agents/{agent_id}/config`, `DELETE /v1/agents/{agent_id}` |
| **Document Ingestion** | `POST /v1/agents/{agent_id}/documents`, `GET /v1/agents/{agent_id}/documents`, `GET /v1/agents/{agent_id}/documents/{doc_id}/status`, `POST /v1/agents/{agent_id}/reindex` *(developer-triggered full reindex — not automatic; required after chunking strategy change)*, `DELETE /v1/agents/{agent_id}/documents/{doc_id}` |
| **Query** | `POST /v1/agents/{agent_id}/query` |
| **Evaluation** | `POST /v1/agents/{agent_id}/eval` *(store or replace golden dataset)*, `POST /v1/agents/{agent_id}/eval/run` *(trigger evaluation run against stored dataset)*, `GET /v1/agents/{agent_id}/eval/history` |
| **Observability** | `GET /v1/metrics`, `GET /v1/health`, `GET /v1/ready` |

### Data Schemas

**Document upload response:**
```json
{ "job_id": "string", "document_id": "string", "status": "queued" }
```
The `job_id` is the handle for polling `GET /v1/agents/{agent_id}/documents/{doc_id}/status`.

**Query request:**
```json
{ "query": "string", "top_k": "integer (optional, agent default used if omitted)" }
```

**Query response:**
```json
{
  "answer": "string",
  "confidence": "float (0.0–1.0)",
  "citations": [
    { "document_name": "string", "chunk_text": "string", "page_reference": "string" }
  ],
  "latency_ms": "integer"
}
```

**Agent config (create/update):**
```json
{
  "name": "string",
  "chunking_strategy": "fixed_size | semantic | hierarchical | document_aware",
  "vector_store": "pgvector | qdrant | pinecone",
  "embedding_provider": "openai | cohere | bedrock",
  "llm_provider": "anthropic | openai | bedrock",
  "retrieval_mode": "dense | sparse | hybrid",
  "top_k": "integer",
  "reranker": "none | cross_encoder | cohere"
}
```

### Rate Limiting

- **Scope:** Per-tenant, per-minute request limits enforced at the API layer
- **Configuration:** Limit configurable per tenant in MongoDB; default limit applied if not set
- **Enforcement:** Hard limit — requests exceeding the limit receive `429 Too Many Requests`
- **Token budgets:** Tracked for visibility via cost observability; hard token budget enforcement is v2

### Error Codes

| HTTP Status | Condition |
|---|---|
| `400 Bad Request` | Invalid request body, missing required fields, unsupported config values |
| `401 Unauthorized` | Missing or invalid API key |
| `403 Forbidden` | Valid API key but cross-tenant access attempt |
| `404 Not Found` | Agent, tenant, or document not found |
| `409 Conflict` | Agent name already exists for tenant |
| `422 Unprocessable Entity` | Reindex required — chunking strategy mismatch, embedding model mismatch, or query issued before reindex completes after a provider change |
| `429 Too Many Requests` | Per-tenant rate limit exceeded |
| `500 Internal Server Error` | Unexpected pipeline failure |
| `503 Service Unavailable` | Dependency unavailable (vector store, LLM provider) |

### API Documentation

- **Format:** OpenAPI 3.0, auto-generated by FastAPI — available at `/docs` (Swagger UI) and `/redoc`
- **SDK:** Out of scope for v1. Comprehensive OpenAPI documentation is sufficient for the target audience (backend engineers). A Python SDK is a planned v2 open-source contribution opportunity.
- **Versioning:** URL path versioning (`/v1/...`) confirmed. Breaking change freedom acceptable for v1 until the first stable release tag.

### Implementation Considerations

- FastAPI chosen for automatic OpenAPI generation, async support, and Python-native type validation
- All request/response bodies are JSON; multipart/form-data for document file upload
- Pagination required on all list endpoints — cursor-based preferred over offset for large collections
- Document upload is idempotent by document hash — re-uploading the same document creates a new version, not a duplicate

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Platform primitive MVP — the minimum that proves the core architectural claim. One of everything working end-to-end: one chunking strategy, one vector store, one embedding provider, one LLM provider. Not a demo, not a prototype — a production-grade slice deployed on real AWS infrastructure. Stage 5 is the first independently demonstrable milestone; Stage 6 completes MVP.

**Resource Requirements:** Single engineer (AI Platform Engineer role). Python only. All infrastructure on AWS via Terraform. Built in public on buildbeyondbackend.com across a 12-stage YouTube series.

### Build Stage Sequence

| Stage | Focus | Milestone |
|---|---|---|
| 1 | Project scaffold, FastAPI skeleton, MongoDB connection, config system, health endpoints | Infrastructure baseline |
| 2 | Tenant and RAG Agent management APIs, MongoDB schemas, API key auth, rate limiting | Tenant/agent layer complete |
| 3 | Document ingestion — parser, PII scrubbing, S3 archive, SQS async queue, status polling | Async ingestion pipeline complete |
| 4 | Fixed-size chunking + OpenAI embeddings + pgvector namespace isolation | Vector store layer complete |
| **5** | **Dense retrieval + generation (Anthropic) + citations + confidence scores** | **🎯 First end-to-end query — independently demonstrable** |
| **6** | **Basic RAGAS eval framework + experiment tracking in MongoDB** | **✅ MVP complete** |
| 7 | Semantic + hierarchical + document-aware chunking strategies + benchmark | Chunking strategies complete |
| 8 | Hybrid search (BM25 + dense + RRF) + reranking (local + Cohere) + benchmark | Full retrieval modes complete |
| 9 | Qdrant backend + Pinecone backend behind abstract interface + benchmark all three | Multi-backend complete |
| 10 | All embedding providers (Cohere, Bedrock) + all LLM providers (OpenAI, Bedrock) + semantic caching | Full provider matrix complete |
| 11 | Full observability — per-stage latency, cost-per-query, metrics endpoint, audit log, regression alerts | Observability complete |
| 12 | AWS deployment via Terraform + GitHub Actions CI-CD with eval gate | Production deployment complete |

Stages 1–4 are infrastructure. Stage 5 is the first independently demonstrable milestone. Stages 6–12 add capability on a proven foundation.

*MVP, Growth, and Vision feature lists: see Product Scope.*

### Risk Mitigation Strategy

**Technical Risks:**

| Risk | Mitigation |
|---|---|
| PII scrubbing false negatives | Presidio Analyzer (Microsoft open-source); target <5% false-negative rate on standard entity types. Defence-in-depth: scrub at ingestion AND at query time. Known limitation documented in README. Zero-tolerance on architectural enforcement — not on detection accuracy. |
| Async ingestion failure | Transient failures (API timeout, S3 error): 3 retries with exponential backoff → DLQ on exhaustion. Permanent failures (corrupt PDF, unsupported format): immediate DLQ, no retries. Ingestion job status updated to `failed` with error reason; caller re-triggers manually. |
| Multi-provider abstraction complexity | Backend-agnostic test suite — same assertions, swapped backend. Sequential validation: pgvector first (proves interface), Qdrant in Stage 9, Pinecone after Qdrant passes. Never validating more than one new backend at a time. |
| MongoDB config-read latency | Connection pooling + request-scoped in-memory config cache (few-second TTL). Config read once per request across all pipeline stages. |

**Market Risks:** TrueRAG targets a real and current pain (RAG replication without standardisation). Market risk is low — the gap between tutorials and enterprise black-boxes is validated. v1 success metric is technical correctness, not adoption; community growth is a v2 concern.

**Resource Risks:** Single-engineer project built in a defined 12-stage sequence. Each stage is independently demonstrable — if work pauses, the last completed stage is a working deliverable. No stage depends on future stages being complete.

## Functional Requirements

### Tenant Management

- **FR1:** Tenant Developer can register a new tenant with a unique identifier
- **FR2:** Platform Admin can list all registered tenants
- **FR3:** Platform Admin can delete a tenant and all associated agents, documents, and data
- **FR4:** System issues an API key to a tenant upon registration

### Agent Management

- **FR5:** Tenant Developer can create a named RAG Agent under their tenant with a full pipeline configuration
- **FR6:** Tenant Developer can update an agent's pipeline configuration at runtime without restarting the service
- **FR7:** Tenant Developer can retrieve an agent's current configuration and status
- **FR8:** Tenant Developer can list all agents registered under their tenant
- **FR9:** Tenant Developer can delete an agent and its isolated namespace
- **FR10:** System warns when a configuration change creates a mismatch with existing ingested data

### Document Management & Ingestion

- **FR11:** Tenant Developer can upload documents (PDF, TXT, Markdown, DOCX) to an agent's knowledge base
- **FR12:** System processes document uploads asynchronously — upload returns a job ID immediately; processing continues in the background
- **FR13:** Tenant Developer can poll ingestion status by job ID to determine when a document is queryable
- **FR14:** Tenant Developer can list all documents ingested into an agent
- **FR15:** Tenant Developer can delete a document and all its associated chunks from an agent's namespace
- **FR16:** System supports document versioning — re-ingesting a document creates a new version with the old version archived
- **FR17:** Tenant Developer can trigger a full reindex of an agent's documents after a pipeline configuration change
- **FR18:** System scrubs PII from document content before any chunk is stored in the vector store
- **FR19:** System archives raw documents to object storage before processing begins
- **FR20:** Every stored chunk carries metadata: tenant, agent, document, chunk index, chunking strategy, timestamp, and version
- **FR57:** System generates and returns a unique document ID on successful upload that the caller uses for status polling and document deletion

### Retrieval Pipeline Configuration

- **FR21:** Tenant Developer can configure chunking strategy per agent (fixed-size, semantic, hierarchical, document-aware)
- **FR22:** Tenant Developer can configure embedding provider per agent (OpenAI, Cohere, AWS Bedrock)
- **FR23:** Tenant Developer can configure vector store backend per agent (pgvector, Qdrant, Pinecone)
- **FR24:** Tenant Developer can configure retrieval mode per agent (dense, sparse, hybrid)
- **FR25:** Tenant Developer can configure reranking per agent (none, local cross-encoder, Cohere Rerank)
- **FR26:** Tenant Developer can configure top-k retrieval count per agent
- **FR27:** Tenant Developer can configure LLM provider and model per agent (Anthropic, OpenAI, AWS Bedrock)
- **FR28:** System enforces namespace isolation — an agent's retrieval cannot access another agent's documents under any condition
- **FR29:** Service Consumer can apply metadata filters to scope retrieval within an agent's namespace
- **FR56:** System detects when an agent's embedding model has changed and flags that existing chunks require re-embedding before retrieval quality is reliable

### Query & Generation

- **FR30:** Service Consumer can submit a natural language query to a RAG Agent via REST API
- **FR31:** System scrubs PII from query text before it reaches the retrieval pipeline or LLM
- **FR32:** System returns a generated answer with citations identifying which chunks and documents contributed
- **FR33:** System returns a confidence score with every generated response
- **FR34:** Service Consumer can request structured JSON output from a query
- **FR35:** System optionally rewrites queries to improve retrieval recall, configurable per agent
- **FR36:** System routes queries — determining whether retrieval is needed or the LLM can answer directly
- **FR37:** System returns a semantic cache hit for queries that match a previous query above a configurable similarity threshold, scoped per agent
- **FR38:** System invalidates an agent's semantic cache when that agent's documents are updated

### Evaluation & Quality

- **FR39:** Tenant Developer can define and store a golden dataset (question/answer pairs) per agent
- **FR40:** Tenant Developer can trigger a RAGAS evaluation run for an agent against its golden dataset
- **FR41:** System stores every evaluation experiment result — configuration snapshot and RAGAS scores — for historical comparison
- **FR42:** System automatically pushes a regression alert when an agent's RAGAS score drops below its configured baseline threshold
- **FR43:** Platform Admin can view evaluation history and score trends per agent
- **FR44:** System exposes evaluation runs as an API endpoint triggerable by CI-CD pipelines

### Observability & Governance

- **FR45:** Platform Admin can retrieve per-tenant and per-agent metrics: query volume, latency breakdown, and cost
- **FR46:** System tracks cost per query including token usage, embedding API calls, and reranker API calls
- **FR47:** System tracks latency per pipeline stage: chunking, embedding, retrieval, reranking, generation
- **FR48:** System writes a tamper-evident audit log entry for every query event containing: tenant ID, agent ID, API key hash, query hash, timestamp, response confidence score
- **FR49:** System exposes health and readiness endpoints for infrastructure monitoring
- **FR55:** System exposes a Prometheus-compatible metrics endpoint for infrastructure monitoring integration

### Security & Access Control

- **FR50:** System authenticates every request using a per-tenant API key passed as a request header
- **FR51:** System rejects requests attempting cross-tenant access at the API boundary before any pipeline logic executes
- **FR52:** System enforces per-tenant per-minute request rate limits configurable per tenant
- **FR53:** System reads all credentials from secrets management at operation time — credential rotation takes effect on the next request without service restart
- **FR54:** AI Platform Engineer can add a new vector store, chunking strategy, or reranker backend by implementing the corresponding abstract interface without modifying core pipeline logic

## Non-Functional Requirements

### Performance

| Requirement | Target | Threshold |
|---|---|---|
| Query p95 latency (retrieval + reranking + generation) | < 3s | > 5s |
| Query p95 latency (without reranking) | < 1.5s | > 3s |
| Ingestion time — 10-page PDF fully queryable | < 60s | > 120s |
| RAGAS faithfulness baseline | > 0.7 | < 0.6 (auto-flag) |

Performance targets apply under the defined scalability envelope (50 concurrent queries). Degradation outside this envelope is acceptable and expected.

### Security

- All data in transit encrypted via TLS 1.2+
- All data at rest encrypted using AWS-managed encryption (S3, DynamoDB, RDS)
- API keys stored in MongoDB — never logged in plaintext, never returned after initial issuance
- All provider credentials (LLM, embedding, vector store) read from AWS Secrets Manager at operation time — never cached at startup, rotation takes effect immediately
- PII scrubbed from document content at ingestion and from query text at query time — zero tolerance for PII reaching the vector store or LLM
- Namespace isolation enforced at the vector store query level — zero tolerance for cross-namespace results
- Audit log entries stored in DynamoDB — query text never written, API key hash only
- No secrets in code, configuration files, or environment variables

### Reliability

- **Query path availability target:** 99.5% (≈ 44 hours downtime per year) — appropriate for a single-engineer project on ECS Fargate with AWS managed services
- **Ingestion path availability:** Best-effort with retry and DLQ. Async ingestion with 3 retries (exponential backoff) and dead letter queue is not classified as an availability failure — it is expected degradation handling
- Transient dependency failures (LLM provider timeout, vector store unavailable): surface `503 Service Unavailable` to caller; do not silently return degraded results
- Ingestion job failures: update job status to `failed` with error reason; caller can re-trigger manually

### Scalability

Designed for internal platform scale at a mid-size organisation. Do not over-engineer beyond this envelope:

| Dimension | Target |
|---|---|
| Concurrent query requests | 50 without degradation |
| Tenants | Up to 50 |
| Agents per tenant | Up to 20 (1,000 total) |
| Documents per agent | Up to 10,000 |
| Concurrent ingestion jobs | 10 without blocking retrieval path |

Async ingestion via SQS ensures ingestion load never degrades the retrieval path — these are separate execution paths. Query path and ingestion path scale independently.

### Maintainability

- Every significant architectural decision documented as an ADR in the repository before implementation begins
- Abstract interfaces (`VectorStore`, `ChunkingStrategy`, `Reranker`) must remain stable — new implementations added without modifying existing interface contracts
- Each of the 12 build stages independently demonstrable — no stage introduces a regression in previously completed stages
- CI-CD pipeline includes RAGAS eval gate — deployments blocked if scores fall below configured thresholds
