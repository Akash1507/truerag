---
stepsCompleted:
  - step-01-init
  - step-02-context
  - step-03-starter
  - step-04-decisions
  - step-05-patterns
  - step-06-structure
  - step-07-validation
  - step-08-complete
lastStep: 8
status: 'complete'
completedAt: '2026-04-17'
inputDocuments:
  - _bmad-output/project-context.md
  - _bmad-output/planning-artifacts/requirements-brief.md
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/implementation-readiness-report-2026-04-17.md
workflowType: 'architecture'
project_name: 'truerag'
user_name: 'Akash'
date: '2026-04-17'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**
57 FRs across 8 capability areas: Tenant Management (4), Agent Management (6), Document Ingestion (11), Retrieval Pipeline Configuration (10), Query & Generation (9), Evaluation & Quality (6), Observability & Governance (6), Security & Access Control (5).

Architecturally, these group into four subsystems:
- **Management plane** — tenant and agent registration, config CRUD, rate limiting
- **Ingestion pipeline** — async document processing, chunking, embedding, vector upsert
- **Query pipeline** — PII scrub, cache check, retrieval, reranking, generation, response assembly
- **Governance layer** — evaluation, observability, audit, cost tracking

**Non-Functional Requirements:**
22 NFRs across 5 categories driving architectural decisions:
- Performance: p95 query < 3s (with reranking), < 1.5s (without); 60s full ingestion
- Security: Zero PII in vector store or LLM context; zero cross-namespace results (both zero-tolerance)
- Reliability: 99.5% query path availability; ingestion path best-effort with DLQ
- Scalability: 50 concurrent queries; 50 tenants; 1,000 total agents; 10,000 docs/agent
- Maintainability: Stable abstract interfaces (VectorStore, ChunkingStrategy, Reranker); ADR per architectural decision; 12-stage independent demonstrability

**Scale & Complexity:**

- Primary domain: API Backend — AI/ML Infrastructure (multi-tenant platform primitive)
- Complexity level: Medium (significant external API fan-out, pipeline orchestration, multi-tenancy, async separation — not enterprise distributed systems scale)
- Estimated architectural components: ~12 (FastAPI app, MongoDB, SQS queue, S3, 3 vector store backends, embedding providers, LLM providers, DynamoDB, ECS Fargate workers, Secrets Manager, semantic cache)

### Technical Constraints & Dependencies

**Fixed by project context (non-negotiable):**
- Python 3.11+ only — no TypeScript, no Go
- FastAPI — REST API, auto-generated OpenAPI 3.0
- MongoDB — all tenant and agent config; dynamic at runtime
- AWS SQS — async ingestion queue
- AWS S3 — raw document archive
- AWS DynamoDB — audit log (separate table) + eval results + ingestion job status
- AWS ECS Fargate — compute for both API and ingestion worker
- AWS Secrets Manager — all credentials; read at operation time, not startup
- Terraform — all infrastructure
- GitHub Actions — CI-CD with RAGAS eval gate
- Single-region: AWS us-east-1 (v1)
- `/v1/` URL prefix enforced from day one

**Pluggable (abstract interface required):**
- Vector stores: pgvector (RDS), Qdrant, Pinecone
- Embedding providers: OpenAI, Cohere, AWS Bedrock
- LLM providers: Anthropic, OpenAI, AWS Bedrock
- Chunking strategies: fixed-size, semantic, hierarchical, document-aware
- Rerankers: none, local cross-encoder, Cohere Rerank

**PII detection:** Microsoft Presidio Analyzer; defence-in-depth (ingestion + query time); <5% false-negative rate target; known limitation to be documented

### Cross-Cutting Concerns Identified

1. **Namespace isolation** — enforced at vector store query level (not application layer); zero-tolerance; every VectorStore interface method must accept namespace as a hard filter
2. **PII scrubbing** — applied at two points: pre-chunk (ingestion) and pre-retrieval (query); Presidio as the implementation; must not be bypassable
3. **Async separation** — ingestion path (SQS consumer worker) and query path (FastAPI handlers) are independent execution units; share no in-process state; ingestion must never starve retrieval
4. **Runtime reconfigurability** — MongoDB config read per-request; request-scoped cache (few-second TTL); config updates take effect on the next request; no service restart required for any provider or strategy change
5. **Secrets rotation** — AWS Secrets Manager read at operation time; credentials never cached at startup; rotation takes effect on the next request without restart
6. **Observability instrumentation** — structured JSON logging + per-stage latency tracking + cost-per-query (tokens, embedding calls, reranker calls) must be wired uniformly across both pipelines; not bolted on per endpoint

## Foundation & Project Scaffold

### Primary Technology Domain

API Backend — AI/ML Infrastructure. Python-only, brownfield project. All technology choices are pre-determined by project context constraints.

### Technology Decisions (Pre-Established)

**Language & Runtime:**
- Python 3.11+
- Async-first — FastAPI with `asyncio`; all I/O-bound operations must be non-blocking

**Web Framework:**
- FastAPI — auto-generated OpenAPI 3.0 at `/docs` (Swagger UI) and `/redoc`
- Uvicorn as ASGI server; Gunicorn as process manager on ECS Fargate
- Pydantic v2 for request/response validation and settings management

**Project Structure:**
```
truerag/
├── app/
│   ├── api/v1/          # FastAPI routers — one module per resource group
│   ├── core/            # Config, auth middleware, rate limiting, dependencies
│   ├── models/          # Pydantic schemas (request/response) + MongoDB documents
│   ├── services/        # Business logic — ingestion service, query service, eval service
│   ├── pipelines/       # Ingestion pipeline + query pipeline orchestration
│   ├── interfaces/      # Abstract base classes: VectorStore, ChunkingStrategy, Reranker
│   ├── providers/       # Concrete implementations: pgvector, openai, anthropic, etc.
│   ├── workers/         # SQS consumer worker — ingestion path
│   └── utils/           # PII scrubbing, observability, secrets client
├── tests/               # pytest — mirrors app/ structure
├── scripts/             # Local dev utilities — not application code
│   ├── seed_tenant.py   # Seed a test tenant and agent for local development
│   ├── run_eval.py      # Run RAGAS eval suite locally against a live agent
│   └── reindex.py       # Trigger manual reindex for an agent (post config change)
├── terraform/           # All AWS infrastructure
├── docs/adrs/           # Architecture Decision Records
└── .github/workflows/   # CI-CD pipeline with RAGAS eval gate
```

**Testing Framework:**
- pytest + pytest-asyncio for async test support
- httpx for FastAPI test client (async)
- Backend-agnostic test suite for abstract interface validation

**Code Quality:**
- Ruff — linting and formatting (replaces flake8 + black)
- mypy — static type checking (strict mode)
- pre-commit hooks enforcing both

**Dependency Management:**
- pip + `pyproject.toml` (PEP 517/518)
- Requirements split: `requirements.txt` (runtime) + `requirements-dev.txt` (test/lint)

**Environment & Secrets:**
- `pydantic-settings` for typed settings from environment variables
- AWS Secrets Manager client wrapper in `app/utils/secrets.py` — called at operation time
- No secrets in `.env` files; `.env` used only for local dev non-secrets (log level, region)

**Note:** Stage 1 of the 12-stage build sequence establishes this scaffold. `scripts/` is available from Stage 2 onwards for local dev workflow. Each subsequent stage adds capability to this foundation without restructuring it.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- D1: MongoDB collection design — defines config store schema used by every pipeline stage
- D3: Async driver stack — every I/O operation depends on this choice
- D8: Vector store namespace format — enforces namespace isolation at the storage level
- D9: SQS queue configuration + message format — ingestion pipeline cannot be built without this
- D12: ECS Fargate topology — two task definitions enforces async separation architecturally

**Important Decisions (Shape Architecture):**
- D2: DynamoDB table design — separate tables per access pattern
- D4: Request-scoped config cache — determines how runtime reconfigurability is implemented
- D5: Semantic cache implementation — determines infrastructure dependencies
- D6: API key format and storage — security foundation
- D7: Rate limiting — in-process for v1
- D10: Error response envelope — consistency across all endpoints
- D11: Pagination cursor format — all list endpoints
- D13: MongoDB hosting — Atlas (managed)
- D14: Qdrant hosting — Qdrant Cloud for v1
- D15: Structured logging format — observability foundation

**Deferred Decisions (Post-MVP / v2):**
- Cross-replica rate limiting accuracy (Redis-backed sliding window) — in-process sufficient for v1 scale
- Multi-region deployment — single-region us-east-1 for v1
- Python SDK — post-v1 open-source contribution opportunity

**Category 4 (Frontend Architecture): Not applicable** — TrueRAG is API-only; no frontend UI in v1.

---

### Data Architecture

**D1 — MongoDB Collections**

| Collection | Purpose | Key Fields |
|---|---|---|
| `tenants` | Tenant record, API key hash, rate limit config | `tenant_id`, `api_key_hash`, `rate_limit_rpm`, `created_at` |
| `agents` | Full agent pipeline config | `agent_id`, `tenant_id`, `name`, `chunking_strategy`, `vector_store`, `embedding_provider`, `llm_provider`, `retrieval_mode`, `top_k`, `reranker`, `semantic_cache_enabled`, `semantic_cache_threshold`, `status`, `created_at`, `updated_at` |
| `eval_datasets` | Golden Q&A pairs per agent | `agent_id`, `tenant_id`, `questions[]`, `created_at` |
| `eval_experiments` | Experiment results — config snapshot + RAGAS scores | `agent_id`, `tenant_id`, `config_snapshot`, `ragas_scores`, `baseline_delta`, `triggered_alert`, `created_at` |
| `semantic_cache` | Cached query vectors + responses, scoped per agent | `agent_id`, `query_vector`, `query_hash`, `response`, `created_at` |

`eval_datasets` and `eval_experiments` remain in MongoDB (config-adjacent, need joint querying with agent context). DynamoDB holds audit log only.

**D2 — DynamoDB Tables**

Two separate tables — divergent access patterns make single-table design counterproductive:

- **`truerag-audit-log`** — partition key: `tenant_id`, sort key: `timestamp#query_hash`
- **`truerag-ingestion-jobs`** — partition key: `job_id` (polled by job ID directly)

**D3 — Async Driver Stack**

| Store | Driver | Notes |
|---|---|---|
| MongoDB | `motor` | Async MongoDB driver; PyMongo-compatible API |
| PostgreSQL / pgvector | `asyncpg` + `sqlalchemy[asyncio]` | asyncpg for raw performance; SQLAlchemy for query building |
| AWS (SQS, S3, DynamoDB, Secrets Manager) | `aioboto3` | Async wrapper around boto3 |

Full async stack — no blocking I/O anywhere in either pipeline.

**D4 — Request-Scoped Config Cache**

Config loaded once per request at the FastAPI dependency layer via `Depends()`. Passed down through all pipeline stages as a dependency-injected object. No TTL complexity, no cross-request caching, no stale-config risk. Config updates take effect on the next request — exact semantics required by the PRD.

**D5 — Semantic Cache Implementation**

Dedicated `pgvector` table (`semantic_cache`) on the same RDS instance as the document chunks — separate table, not mixed with document vectors. TTL enforced via `created_at` column + periodic cleanup. Namespace-scoped by `agent_id`. Avoids Redis as a new infrastructure dependency. Cache invalidated on document update by deleting all rows for the `agent_id`.

---

### Authentication & Security

**D6 — API Key Format and Storage**

- Generated: `secrets.token_urlsafe(32)` — 256 bits of entropy, URL-safe
- Stored in MongoDB (`tenants` collection): SHA-256 hash only — raw key never persisted
- Returned to caller: raw key, once, at tenant registration — never retrievable again
- Request header: `X-API-Key`
- Audit log: `api_key_hash` field = SHA-256 of the raw key

**D7 — Rate Limiting**

In-process fixed window counter per tenant, per minute. FastAPI middleware reads limit from the agent's tenant config (loaded via `Depends()`). At 50 tenants and internal platform scale, in-process is sufficient. Worst-case with multiple ECS replicas: each task independently enforces the limit — acceptable over-allowance for v1. Redis-backed sliding window deferred to v2.

**D8 — Vector Store Namespace Format**

```
{tenant_id}_{agent_id}
```

Both IDs are MongoDB ObjectIds (24-char hex). Combined string is deterministic, unique per agent, and safe for pgvector schema names, Qdrant collection names, and Pinecone namespace strings. Used as the hard filter on every vector store query — not derivable from application logic alone.

---

### API & Communication Patterns

**D9 — SQS Queue Configuration**

- **Type:** Standard queue (not FIFO) — ingestion order irrelevant; throughput over ordering
- **Visibility timeout:** 300s — generous for large PDF processing
- **Max receive count:** 3 → DLQ on exhaustion
- **DLQ retention:** 14 days
- **Message format:**
```json
{
  "job_id": "string",
  "tenant_id": "string",
  "agent_id": "string",
  "document_id": "string",
  "s3_key": "string",
  "file_type": "pdf | txt | md | docx",
  "timestamp": "ISO8601"
}
```

**D10 — Error Response Envelope**

All `4xx` and `5xx` responses:
```json
{
  "error": {
    "code": "MACHINE_READABLE_CONSTANT",
    "message": "Human-readable description",
    "request_id": "UUID"
  }
}
```
`request_id` generated at request entry, injected into all structured log entries for the request — primary log correlation handle.

**D11 — Pagination Cursor Format**

Cursor = base64-encoded MongoDB ObjectId of the last document in the page. Passed as `?cursor=<value>` query parameter. Opaque to callers. Efficient for MongoDB range queries (`_id > decoded_cursor`). Applied to all list endpoints.

---

### Infrastructure & Deployment

**D12 — ECS Fargate Topology**

Two independent ECS services, two task definitions:

| Service | Task | Scales On | Notes |
|---|---|---|---|
| `truerag-api` | FastAPI + Uvicorn + Gunicorn | CPU / request count | No SQS consumer |
| `truerag-worker` | SQS consumer + ingestion pipeline | SQS queue depth | No HTTP listener |

Services share no in-process state. This is the architectural enforcement of the async separation requirement — not a convention, a topology constraint.

**D13 — MongoDB Hosting**

MongoDB Atlas (managed) — free tier sufficient for v1, native AWS VPC peering to us-east-1, zero ops overhead, automatic backups. Self-hosting on EC2 deferred to v2 if cost or compliance demands it.

**D14 — Qdrant Hosting (Stage 9+)**

Qdrant Cloud (managed) for v1. Self-hosted on ECS deferred to v2 if cost warrants it.

**D15 — Structured Logging Format**

Every log entry across both API and worker:
```json
{
  "timestamp": "ISO8601",
  "level": "INFO | WARNING | ERROR",
  "tenant_id": "string | null",
  "agent_id": "string | null",
  "request_id": "string",
  "operation": "string",
  "latency_ms": "integer | null",
  "extra": {}
}
```
Output: stdout → CloudWatch Logs via ECS awslogs log driver. No third-party log aggregation in v1.

---

### Decision Impact Analysis

**Implementation Sequence (order matters):**
1. D3 (async driver stack) — install and configure before any service code
2. D15 (logging format) — wire into app startup before any business logic
3. D6 (API key) + D8 (namespace format) — Stage 2 foundations
4. D1 (MongoDB schema) + D2 (DynamoDB tables) — Stage 2, before any CRUD
5. D9 (SQS config + message format) — Stage 3, before ingestion worker
6. D4 (request-scoped config cache) — Stage 3, wired into pipeline orchestration
7. D12 (ECS topology) — Stage 12, but Terraform scaffolded from Stage 1
8. D5 (semantic cache) + D7 (rate limiting) — Growth features, post-MVP

**Cross-Component Dependencies:**
- D8 (namespace format) → every VectorStore interface method signature must accept namespace
- D4 (config cache) → FastAPI `Depends()` chain must be designed to pass config object through entire pipeline depth
- D10 (request_id) → must be generated in middleware before any handler executes, propagated to audit log (D2) and all log entries (D15)
- D9 (SQS message format) → `document_id` in message must match the ID returned to the caller at upload time (FR57)

## Implementation Patterns & Consistency Rules

**Critical conflict points identified: 8 categories** where AI agents could make divergent choices and produce incompatible code.

### Naming Patterns

**Python Code (PEP 8 — no exceptions):**
- Files and modules: `snake_case.py` — e.g., `pgvector_store.py`, `openai_embedder.py`
- Classes: `PascalCase` — e.g., `PgVectorStore`, `OpenAIEmbedder`, `FixedSizeChunker`
- Functions and methods: `snake_case` — e.g., `get_agent_config()`, `scrub_pii()`
- Variables and parameters: `snake_case` — e.g., `agent_id`, `tenant_id`, `top_k`
- Constants: `UPPER_SNAKE_CASE` — e.g., `MAX_RETRY_COUNT = 3`

**MongoDB Fields:**
- All field names: `snake_case` — no camelCase in any collection document
- IDs: always `{entity}_id` as the logical name; MongoDB `_id` used as the physical key
- Timestamps: always `created_at` and `updated_at` — never `createdAt`, `timestamp`, or `date`

**API JSON Fields:**
- All request and response body fields: `snake_case` — Pydantic models enforce this; no aliasing to camelCase
- Path parameters: `snake_case` — e.g., `/v1/agents/{agent_id}/documents/{document_id}`
- Query parameters: `snake_case` — e.g., `?cursor=...`, `?top_k=10`

**Abstract Interface Method Names (locked — never renamed):**
```python
# VectorStore
upsert(namespace: str, vectors: list[VectorRecord]) -> None
query(namespace: str, vector: list[float], top_k: int, filters: dict | None) -> list[VectorResult]
delete_namespace(namespace: str) -> None
health() -> bool

# ChunkingStrategy
chunk(text: str, metadata: ChunkMetadata) -> list[Chunk]

# Reranker
rerank(query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]

# EmbeddingProvider
embed(texts: list[str]) -> list[list[float]]

# LLMProvider
generate(prompt: str, context: list[Chunk]) -> str
```

**Ingestion Job Status Values (string constants — never hardcoded inline):**
```python
class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
```

---

### Structure Patterns

**Provider Registration:**
All pluggable providers (vector stores, chunkers, rerankers, embedding providers, LLM providers) are registered in `app/providers/registry.py`. The registry maps config string values to concrete classes. New providers are added here — nowhere else.

```python
VECTOR_STORE_REGISTRY: dict[str, type[VectorStore]] = {
    "pgvector": PgVectorStore,
    "qdrant": QdrantVectorStore,
    "pinecone": PineconeVectorStore,
}
```

**Test Location:**
All tests in `tests/` mirroring `app/` structure exactly:
- `tests/api/v1/test_agents.py` mirrors `app/api/v1/agents.py`
- `tests/providers/test_pgvector_store.py` mirrors `app/providers/pgvector_store.py`
- Never co-located alongside source files

**FastAPI Router Registration:**
Each resource group has its own router file in `app/api/v1/`. All routers registered in `app/api/v1/__init__.py`. No routes defined directly in `main.py`.

---

### Format Patterns

**Success Response:**
No envelope wrapper for single-resource responses — return the resource object directly. List responses use:
```json
{
  "items": [...],
  "next_cursor": "string | null"
}
```

**Error Response:**
```json
{
  "error": {
    "code": "MACHINE_READABLE_CONSTANT",
    "message": "Human-readable string",
    "request_id": "UUID"
  }
}
```

**Error Code Constants:**
Defined as an enum in `app/core/errors.py` — never hardcoded as strings inline:
```python
class ErrorCode(str, Enum):
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    NAMESPACE_VIOLATION = "NAMESPACE_VIOLATION"
    PII_DETECTED = "PII_DETECTED"
    CHUNKING_STRATEGY_MISMATCH = "CHUNKING_STRATEGY_MISMATCH"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
```

**Datetime Handling:**
- Always `datetime.now(datetime.timezone.UTC)` — never `datetime.utcnow()` (deprecated in Python 3.12; returns naive datetime)
- Always serialized as ISO 8601 UTC string in API responses: `"2026-04-17T12:00:00Z"`
- Always stored as UTC in MongoDB and DynamoDB

---

### Communication Patterns

**Pipeline Stage Error Handling:**
Raise typed exceptions — never return `None` or error dicts from pipeline stages:

```python
class TrueRAGError(Exception): ...
class NamespaceViolationError(TrueRAGError): ...
class PIIDetectedError(TrueRAGError): ...
class ProviderUnavailableError(TrueRAGError): ...
class IngestionError(TrueRAGError): ...
```

FastAPI exception handlers in `app/core/exception_handlers.py` map typed exceptions to the standard error envelope. No raw `HTTPException` raises in business logic — only in the API layer.

**Secrets Access:**
Always via `app/utils/secrets.py` wrapper — never direct `aioboto3` calls in providers or services. Single point for Secrets Manager reads; ensures "read at operation time" is enforced consistently and is mockable in tests.

**Logging:**
Always via the structured logger from `app/utils/observability.py` — never `print()`, never `import logging` directly. Every log call must include `tenant_id`, `agent_id`, `request_id`, and `operation` from request context.

**PII Scrubbing:**
Called explicitly — not via middleware or decorator. Both call sites (ingestion pipeline pre-chunk; query pipeline pre-retrieval) call `scrub_pii()` from `app/utils/pii.py` directly. Keeps scrubbing visible in both pipeline flows and prevents silent bypass through middleware refactoring.

**Retry Logic:**
Implemented once in `app/utils/retry.py` as a decorator. All retryable external calls (embedding provider, LLM provider, vector store) use it. Never reimplemented per-provider.

---

### Enforcement Guidelines

**All agents MUST:**
- Never bypass the provider registry — instantiate providers only through `app/providers/registry.py`
- Never call Secrets Manager directly — always use `app/utils/secrets.py`
- Never call the structured logger as `print()` or stdlib `logging` — always use `app/utils/observability.py`
- Never hardcode namespace strings — always derive from `{tenant_id}_{agent_id}` formula
- Never define error codes as inline strings — always use `ErrorCode` enum from `app/core/errors.py`
- Never add routes to `main.py` — always use resource-specific router files in `app/api/v1/`
- Never implement retry logic inline — always use the retry decorator from `app/utils/retry.py`
- Never use `datetime.utcnow()` — always use `datetime.now(datetime.timezone.UTC)`. `utcnow()` is deprecated in Python 3.12 and returns a naive datetime; `datetime.now(UTC)` returns a timezone-aware UTC datetime.
- Never instantiate pipeline components (chunker, embedder, vector store, reranker, LLM provider, embedding provider) directly inside service functions — always resolve through the provider registry and inject via `Depends()`. This rule applies to all five abstract interfaces: `VectorStore`, `ChunkingStrategy`, `Reranker`, `EmbeddingProvider`, and `LLMProvider` — not just the first three:

```python
# NEVER — direct instantiation bypasses registry and breaks the extension model
def query_service():
    store = PgVectorStore()  # wrong

# ALWAYS — resolved through registry via FastAPI dependency injection
def query_service(vector_store: VectorStore = Depends(get_vector_store)):
    ...  # correct
```

This rule ensures that new provider implementations registered in `app/providers/registry.py` are automatically available without any changes to service or pipeline code.

## Project Structure & Boundaries

### Complete Project Directory Structure

```
truerag/
│
├── pyproject.toml                     # PEP 517/518 — project metadata, tool config
├── requirements.txt                   # Runtime dependencies
├── requirements-dev.txt               # Test + lint dependencies
├── .env.example                       # Non-secret local dev vars template (log level, region)
├── .gitignore
├── README.md
│
├── app/
│   ├── main.py                        # FastAPI app factory, lifespan, router registration
│   │
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py            # Registers all routers
│   │       ├── tenants.py             # FR1-4: POST/GET/DELETE /v1/tenants
│   │       ├── agents.py              # FR5-10: POST/GET/PATCH/DELETE /v1/agents
│   │       ├── documents.py           # FR11-17, FR57: upload, status, list, delete, reindex
│   │       ├── query.py               # FR30-38: POST /v1/agents/{id}/query
│   │       ├── eval.py                # FR39-44: POST/GET /v1/agents/{id}/eval
│   │       └── observability.py       # FR45-49, FR55: /v1/metrics, /v1/health, /v1/ready
│   │
│   ├── core/
│   │   ├── auth.py                    # FR50-51: X-API-Key middleware, tenant resolution
│   │   ├── rate_limiter.py            # FR52: per-tenant fixed window counter
│   │   ├── config.py                  # pydantic-settings — typed app settings
│   │   ├── dependencies.py            # FastAPI Depends() providers for all pipeline components
│   │   ├── errors.py                  # ErrorCode enum + TrueRAGError exception hierarchy
│   │   └── exception_handlers.py      # Maps typed exceptions → standard error envelope
│   │
│   ├── models/
│   │   ├── tenant.py                  # Tenant Pydantic + MongoDB document schema
│   │   ├── agent.py                   # Agent config schema (all pipeline config fields)
│   │   ├── document.py                # Document record + ingestion job status schema
│   │   ├── chunk.py                   # Chunk + VectorRecord + VectorResult types
│   │   ├── eval.py                    # EvalDataset, EvalExperiment, RAGASScores schemas
│   │   └── audit.py                   # AuditLogEntry schema (DynamoDB)
│   │
│   ├── services/
│   │   ├── tenant_service.py          # Tenant CRUD, API key generation + hashing
│   │   ├── agent_service.py           # Agent CRUD, config mismatch detection (FR10, FR56)
│   │   ├── ingestion_service.py       # Document upload orchestration, S3 archive, SQS enqueue
│   │   ├── query_service.py           # Query orchestration — cache → retrieve → rerank → generate → audit
│   │   ├── eval_service.py            # RAGAS eval runs, experiment storage, regression detection
│   │   │                              # FR42: on regression, writes metric to CloudWatch;
│   │   │                              # alarm configured in Terraform triggers notification.
│   │   │                              # Actual push (email/Slack) is v2.
│   │   └── metrics_service.py         # Cost + latency aggregation, Prometheus formatting
│   │
│   ├── pipelines/
│   │   ├── ingestion/
│   │   │   ├── pipeline.py            # Ingestion pipeline orchestrator (called by worker)
│   │   │   ├── parser.py              # PDF/TXT/MD/DOCX → raw text extraction
│   │   │   └── embedder.py            # Chunk → vector (calls EmbeddingProvider via registry)
│   │   └── query/
│   │       ├── pipeline.py            # Query pipeline orchestrator (called by query_service)
│   │       ├── rewriter.py            # FR35: optional query expansion
│   │       ├── router.py              # FR36: retrieval-needed vs direct-LLM routing
│   │       └── generator.py           # FR32-33: context injection, answer + citations + confidence
│   │
│   ├── interfaces/
│   │   ├── vector_store.py            # VectorStore ABC: upsert, query, delete_namespace, health
│   │   ├── chunking_strategy.py       # ChunkingStrategy ABC: chunk(text, metadata) → list[Chunk]
│   │   ├── reranker.py                # Reranker ABC: rerank(query, chunks, top_k) → list[Chunk]
│   │   ├── embedding_provider.py      # EmbeddingProvider ABC: embed(texts) → list[list[float]]
│   │   └── llm_provider.py            # LLMProvider ABC: generate(prompt, context) → str
│   │
│   ├── providers/
│   │   ├── registry.py                # Central registry — maps config strings to all 5 provider types
│   │   ├── vector_stores/
│   │   │   ├── pgvector.py            # MVP (Stage 4): asyncpg + pgvector
│   │   │   ├── qdrant.py              # Stage 9: Qdrant Cloud
│   │   │   └── pinecone.py            # Stage 9: Pinecone managed
│   │   ├── chunking/
│   │   │   ├── fixed_size.py          # MVP (Stage 4): token-count split with overlap
│   │   │   ├── semantic.py            # Stage 7: meaning-boundary split
│   │   │   ├── hierarchical.py        # Stage 7: small retrieval chunks + parent context
│   │   │   └── document_aware.py      # Stage 7: structure-aware (headings, tables)
│   │   ├── embedding/
│   │   │   ├── openai.py              # MVP (Stage 4): OpenAI embeddings
│   │   │   ├── cohere.py              # Stage 10: Cohere Embed
│   │   │   └── bedrock.py             # Stage 10: AWS Bedrock embeddings
│   │   ├── llm/
│   │   │   ├── anthropic.py           # MVP (Stage 5): Anthropic Claude
│   │   │   ├── openai.py              # Stage 10: OpenAI GPT
│   │   │   └── bedrock.py             # Stage 10: AWS Bedrock LLMs
│   │   ├── rerankers/
│   │   │   ├── passthrough.py         # MVP: reranker=none — returns chunks unchanged
│   │   │   ├── cross_encoder.py       # Stage 8: local cross-encoder
│   │   │   └── cohere.py              # Stage 8: Cohere Rerank API
│   │   └── cache/
│   │       └── semantic_cache.py      # D5: pgvector table for semantic cache — lookup,
│   │                                  # store, invalidate by agent_id. Registry pattern applies.
│   │
│   ├── workers/
│   │   ├── sqs_consumer.py            # SQS long-poll loop, message dispatch, DLQ handling
│   │   └── ingestion_worker.py        # Processes one job: parse→scrub→chunk→embed→upsert
│   │
│   └── utils/
│       ├── secrets.py                 # FR53: AWS Secrets Manager wrapper — read at operation time
│       ├── pii.py                     # FR18, FR31: Presidio Analyzer wrapper — scrub_pii()
│       ├── observability.py           # Structured logger factory, per-stage latency tracker
│       ├── retry.py                   # Exponential backoff decorator (3 retries)
│       └── pagination.py             # Cursor encode/decode (base64 ObjectId)
│
├── tests/
│   ├── conftest.py                    # Shared fixtures: test app, mock MongoDB, mock SQS
│   ├── api/
│   │   └── v1/
│   │       ├── test_tenants.py
│   │       ├── test_agents.py
│   │       ├── test_documents.py
│   │       ├── test_query.py
│   │       ├── test_eval.py
│   │       └── test_observability.py
│   ├── services/
│   │   ├── test_tenant_service.py
│   │   ├── test_agent_service.py
│   │   ├── test_ingestion_service.py
│   │   ├── test_query_service.py
│   │   └── test_eval_service.py
│   ├── pipelines/
│   │   ├── test_ingestion_pipeline.py
│   │   └── test_query_pipeline.py
│   ├── providers/
│   │   ├── test_pgvector_store.py     # Backend-agnostic suite — same assertions, swapped backend
│   │   ├── test_qdrant_store.py
│   │   ├── test_pinecone_store.py
│   │   ├── test_fixed_size_chunker.py
│   │   ├── test_openai_embedder.py
│   │   ├── test_cohere_reranker.py
│   │   └── test_semantic_cache.py
│   ├── utils/
│   │   ├── test_pii.py
│   │   └── test_retry.py
│   └── integration/
│       ├── test_ingestion_e2e.py      # Full ingestion path against real backends
│       └── test_query_e2e.py          # Full query path against real backends
│
├── scripts/
│   ├── seed_tenant.py                 # Seed test tenant + agent for local dev (Stage 2+)
│   ├── run_eval.py                    # Run RAGAS eval suite locally against live agent
│   └── reindex.py                     # Trigger manual reindex for an agent
│
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── modules/
│   │   ├── ecs/                       # ECS Fargate — api + worker task definitions
│   │   ├── rds/                       # RDS PostgreSQL with pgvector extension
│   │   ├── sqs/                       # Ingestion queue + DLQ
│   │   ├── s3/                        # Document archive bucket
│   │   ├── dynamodb/                  # Audit log table + ingestion jobs table
│   │   ├── cloudwatch/                # Alarms — including RAGAS regression metric alarm (FR42)
│   │   ├── secrets/                   # Secrets Manager entries (no values in TF)
│   │   └── networking/                # VPC, subnets, security groups
│   └── environments/
│       ├── dev/
│       └── prod/
│
├── docs/
│   └── adrs/
│       └── README.md                  # ADR index — one file per architectural decision
│
└── .github/
    └── workflows/
        ├── ci.yml                     # Lint, type-check, unit + integration tests
        └── deploy.yml                 # Build, push to ECR, update ECS — blocked by RAGAS gate
```

---

### Architectural Boundaries

**API Boundary (external entry point):**
All external traffic enters through `app/api/v1/`. Every request passes through `app/core/auth.py` (API key → tenant resolution) then `app/core/rate_limiter.py` before any handler executes. Cross-tenant access rejected here — no business logic runs if tenant resolution fails.

**Service Boundary (business logic):**
API handlers call service functions only — never pipelines, never providers directly. Services in `app/services/` own business rules. Pipelines in `app/pipelines/` own execution sequence. API handlers stay thin and testable without pipeline complexity.

**Pipeline Boundary (execution sequence):**
Pipelines call abstract interfaces only — never concrete provider classes. The registry in `app/providers/registry.py` resolves config strings to implementations. Runtime reconfigurability is enforced structurally here — pipelines cannot hardcode provider choices.

**Worker Boundary (async separation):**
`app/workers/` is the only code that runs in the `truerag-worker` ECS task. It shares `app/pipelines/ingestion/`, `app/providers/`, and `app/utils/` with the API task but has no FastAPI app, no HTTP listener, and no access to query pipeline code. Enforced by ECS task definition — not convention.

**Data Boundary:**

| Store | Accessed By | Via |
|---|---|---|
| MongoDB | `app/services/`, `app/core/dependencies.py` | `motor` |
| DynamoDB | `app/services/ingestion_service.py` (jobs), `app/services/query_service.py` (audit) | `aioboto3` |
| pgvector (RDS) | `app/providers/vector_stores/pgvector.py`, `app/providers/cache/semantic_cache.py` only | `asyncpg` |
| S3 | `app/services/ingestion_service.py` (archive), `app/workers/ingestion_worker.py` (read) | `aioboto3` |
| SQS | `app/services/ingestion_service.py` (enqueue), `app/workers/sqs_consumer.py` (consume) | `aioboto3` |
| CloudWatch | `app/services/eval_service.py` (regression metric writes) | `aioboto3` |
| Secrets Manager | `app/utils/secrets.py` only — no other file | `aioboto3` |

---

### FR Category to Structure Mapping

| FR Category | Primary Location |
|---|---|
| Tenant Management (FR1-4) | `app/api/v1/tenants.py` · `app/services/tenant_service.py` · `app/models/tenant.py` |
| Agent Management (FR5-10, FR56) | `app/api/v1/agents.py` · `app/services/agent_service.py` · `app/models/agent.py` |
| Document Ingestion (FR11-20, FR57) | `app/api/v1/documents.py` · `app/services/ingestion_service.py` · `app/pipelines/ingestion/` · `app/workers/` |
| Retrieval Pipeline Config (FR21-29) | `app/providers/` (all subdirs) · `app/interfaces/` · `app/providers/registry.py` |
| Query & Generation (FR30-38) | `app/api/v1/query.py` · `app/services/query_service.py` · `app/pipelines/query/` · `app/providers/cache/semantic_cache.py` |
| Evaluation & Quality (FR39-44) | `app/api/v1/eval.py` · `app/services/eval_service.py` · `app/models/eval.py` · `terraform/modules/cloudwatch/` |
| Observability & Governance (FR45-49, FR55) | `app/api/v1/observability.py` · `app/services/metrics_service.py` · `app/utils/observability.py` |
| Security & Access Control (FR50-54) | `app/core/auth.py` · `app/core/rate_limiter.py` · `app/utils/secrets.py` · `app/utils/pii.py` |

---

### Data Flow

**Ingestion path:**
`POST /v1/agents/{id}/documents` → `ingestion_service` → S3 archive → SQS enqueue → DynamoDB job=QUEUED → `[async]` worker dequeues → `ingestion_pipeline` → parse → `pii.scrub_pii()` → chunker (via registry) → embedder (via registry) → vector store `upsert()` → DynamoDB job=READY

**Query path:**
`POST /v1/agents/{id}/query` → auth → rate limit → `query_service` → `pii.scrub_pii()` → `semantic_cache` lookup → `query_pipeline` → optional rewrite → vector store `query()` → optional `reranker.rerank()` → `generator` (LLM provider via registry) → DynamoDB audit log entry → response with citations + confidence

**Regression alert path (FR42):**
`eval_service` completes RAGAS run → score < baseline threshold → writes custom metric to CloudWatch → CloudWatch alarm triggers → SNS notification (v1: email via Terraform-configured alarm; v2: Slack/webhook push)

## Architecture Validation Results

### Coherence Validation ✅

All technology decisions are compatible and mutually reinforcing. Full async stack (`motor`, `asyncpg`, `aioboto3`) with no blocking I/O. Patterns consistently applied across all five abstract interfaces and the provider registry. ECS topology structurally enforces async separation — not convention.

**One implementation constraint:** RAGAS is synchronous. `eval_service.py` must run RAGAS calls via `asyncio.get_event_loop().run_in_executor()` to avoid blocking the event loop. Not a gap — an implementation note for the eval story.

### Requirements Coverage Validation ✅

All 57 FRs mapped to specific files and directories. All 22 NFRs addressed architecturally. Full coverage confirmed — see FR Category to Structure Mapping table in Project Structure section.

**NFR architectural mechanisms summary:**

| NFR Area | Architectural Mechanism |
|---|---|
| p95 query latency | Async stack + semantic cache + request-scoped config; ingestion path cannot starve query |
| 60s ingestion | SQS async decoupling; async embedding calls |
| Zero PII | `pii.scrub_pii()` called explicitly at two points; not bypassable via middleware |
| Zero cross-namespace | `namespace` hard-filter on all VectorStore interface method signatures |
| Credential rotation | `secrets.py` reads at operation time — rotation takes effect on next request |
| 99.5% query availability | ECS Fargate + ALB; ingestion path failure cannot affect query task |
| Ingestion best-effort | SQS 3 retries → DLQ; job status updated to `failed` with error reason |
| 503 on dependency failure | `ProviderUnavailableError` → exception handler → HTTP 503 |
| Stable abstract interfaces | `app/interfaces/` — locked method signatures, never modified |
| RAGAS eval gate | `deploy.yml` blocks deployment below configured threshold |

### Gap Analysis

**Critical gaps:** None — no blockers for implementation.

**Important implementation constraints (story-level, not architecture-level):**

1. **Semantic cache invalidation (FR38):** `ingestion_service.py` must call `semantic_cache.invalidate(agent_id)` at two explicit points — on document ingestion completion and on document deletion. Cross-service dependency; must be explicit in ingestion story acceptance criteria.

2. **Document versioning (FR16):** `document.py` model requires a `version` integer field. `ingestion_service.py` must implement hash-based deduplication: compare incoming document hash against existing records for the `agent_id`; increment version on match; archive previous version. Specify in document ingestion story.

**Nice-to-have:**
- RAGAS sync wrapper: `eval_service.py` uses `run_in_executor()` — capture in eval story.
- `scripts/` utilities access TrueRAG via the REST API only — no direct DB access.

### Architecture Completeness Checklist

- [x] Project context and constraints analysed
- [x] Scale and complexity assessed (medium — 50 tenants, 1,000 agents, 50 concurrent queries)
- [x] 15 architectural decisions documented (D1–D15)
- [x] 5 abstract interfaces with locked method signatures
- [x] Central provider registry pattern defined
- [x] 9 enforcement guidelines — all agents MUST rules
- [x] Complete project directory tree with file-level comments
- [x] All 57 FRs mapped to specific locations
- [x] All 22 NFRs architecturally addressed
- [x] Data boundaries table — every store, accessor, and driver
- [x] Two data flows documented (ingestion + query)
- [x] Regression alert path defined (eval → CloudWatch → SNS)
- [x] Two implementation constraints identified for story capture
- [x] 12-stage build sequence reflected in provider file stage markers

### Architecture Readiness Assessment

**Overall status: READY FOR IMPLEMENTATION**

**Confidence level: High**

**Key strengths:**
- Runtime reconfigurability enforced structurally (registry + DI) — not bypassable by agents
- Async separation guaranteed by ECS topology — ingestion cannot starve query path
- All five extension points (`VectorStore`, `ChunkingStrategy`, `Reranker`, `EmbeddingProvider`, `LLMProvider`) subject to identical registry + DI pattern — consistent extensibility model
- Zero-tolerance constraints (namespace isolation, PII scrubbing) enforced at architectural level — single utility modules, explicit call sites, no middleware bypass possible
- 12-stage build sequence reflected in structure — every stage independently demonstrable without restructuring

**Areas for future enhancement (v2):**
- Redis-backed rate limiting for cross-replica accuracy
- Multi-region deployment
- Hard per-tenant token budget enforcement
- Slack/webhook push for regression alerts (v1 uses CloudWatch alarm)
- Python SDK

### Implementation Handoff

**First implementation step:** Stage 1 scaffold — `app/main.py`, `app/core/config.py`, `app/core/errors.py`, `app/utils/observability.py`, health/readiness endpoints, MongoDB connection via `motor`. All patterns established here propagate through all 12 stages.

**AI Agent Guidelines:**
- Follow all architectural decisions exactly as documented (D1–D15)
- Use implementation patterns consistently — Enforcement Guidelines section is the rule set
- Respect project structure and boundaries — no routes in `main.py`, no direct provider instantiation
- Resolve any ambiguity by checking the FR-to-structure mapping table before adding new files
- Capture semantic cache invalidation and document versioning constraints in story acceptance criteria before implementation begins
