---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
---

# truerag - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for truerag, decomposing the requirements from the PRD and Architecture into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: Tenant Developer can register a new tenant with a unique identifier
FR2: Platform Admin can list all registered tenants
FR3: Platform Admin can delete a tenant and all associated agents, documents, and data
FR4: System issues an API key to a tenant upon registration
FR5: Tenant Developer can create a named RAG Agent under their tenant with a full pipeline configuration
FR6: Tenant Developer can update an agent's pipeline configuration at runtime without restarting the service
FR7: Tenant Developer can retrieve an agent's current configuration and status
FR8: Tenant Developer can list all agents registered under their tenant
FR9: Tenant Developer can delete an agent and its isolated namespace
FR10: System warns when a configuration change creates a mismatch with existing ingested data
FR11: Tenant Developer can upload documents (PDF, TXT, Markdown, DOCX) to an agent's knowledge base
FR12: System processes document uploads asynchronously — upload returns a job ID immediately; processing continues in the background
FR13: Tenant Developer can poll ingestion status by job ID to determine when a document is queryable
FR14: Tenant Developer can list all documents ingested into an agent
FR15: Tenant Developer can delete a document and all its associated chunks from an agent's namespace
FR16: System supports document versioning — re-ingesting a document creates a new version with the old version archived
FR17: Tenant Developer can trigger a full reindex of an agent's documents after a pipeline configuration change
FR18: System scrubs PII from document content before any chunk is stored in the vector store
FR19: System archives raw documents to object storage before processing begins
FR20: Every stored chunk carries metadata: tenant, agent, document, chunk index, chunking strategy, timestamp, and version
FR21: Tenant Developer can configure chunking strategy per agent (fixed-size, semantic, hierarchical, document-aware)
FR22: Tenant Developer can configure embedding provider per agent (OpenAI, Cohere, AWS Bedrock)
FR23: Tenant Developer can configure vector store backend per agent (pgvector, Qdrant, Pinecone)
FR24: Tenant Developer can configure retrieval mode per agent (dense, sparse, hybrid)
FR25: Tenant Developer can configure reranking per agent (none, local cross-encoder, Cohere Rerank)
FR26: Tenant Developer can configure top-k retrieval count per agent
FR27: Tenant Developer can configure LLM provider and model per agent (Anthropic, OpenAI, AWS Bedrock)
FR28: System enforces namespace isolation — an agent's retrieval cannot access another agent's documents under any condition
FR29: Service Consumer can apply metadata filters to scope retrieval within an agent's namespace
FR30: Service Consumer can submit a natural language query to a RAG Agent via REST API
FR31: System scrubs PII from query text before it reaches the retrieval pipeline or LLM
FR32: System returns a generated answer with citations identifying which chunks and documents contributed
FR33: System returns a confidence score with every generated response
FR34: Service Consumer can request structured JSON output from a query
FR35: System optionally rewrites queries to improve retrieval recall, configurable per agent
FR36: System routes queries — determining whether retrieval is needed or the LLM can answer directly
FR37: System returns a semantic cache hit for queries that match a previous query above a configurable similarity threshold, scoped per agent
FR38: System invalidates an agent's semantic cache when that agent's documents are updated
FR39: Tenant Developer can define and store a golden dataset (question/answer pairs) per agent
FR40: Tenant Developer can trigger a RAGAS evaluation run for an agent against its golden dataset
FR41: System stores every evaluation experiment result — configuration snapshot and RAGAS scores — for historical comparison
FR42: System automatically pushes a regression alert when an agent's RAGAS score drops below its configured baseline threshold
FR43: Platform Admin can view evaluation history and score trends per agent
FR44: System exposes evaluation runs as an API endpoint triggerable by CI-CD pipelines
FR45: Platform Admin can retrieve per-tenant and per-agent metrics: query volume, latency breakdown, and cost
FR46: System tracks cost per query including token usage, embedding API calls, and reranker API calls
FR47: System tracks latency per pipeline stage: chunking, embedding, retrieval, reranking, generation
FR48: System writes a tamper-evident audit log entry for every query event containing: tenant ID, agent ID, API key hash, query hash, timestamp, response confidence score
FR49: System exposes health and readiness endpoints for infrastructure monitoring
FR50: System authenticates every request using a per-tenant API key passed as a request header
FR51: System rejects requests attempting cross-tenant access at the API boundary before any pipeline logic executes
FR52: System enforces per-tenant per-minute request rate limits configurable per tenant
FR53: System reads all credentials from secrets management at operation time — credential rotation takes effect on the next request without service restart
FR54: AI Platform Engineer can add a new vector store, chunking strategy, or reranker backend by implementing the corresponding abstract interface without modifying core pipeline logic
FR55: System exposes a Prometheus-compatible metrics endpoint for infrastructure monitoring integration
FR56: System detects when an agent's embedding model has changed and flags that existing chunks require re-embedding before retrieval quality is reliable
FR57: System generates and returns a unique document ID on successful upload that the caller uses for status polling and document deletion

### NonFunctional Requirements

NFR1: Query p95 latency (retrieval + reranking + generation) < 3s; failure threshold > 5s
NFR2: Query p95 latency (without reranking) < 1.5s; failure threshold > 3s
NFR3: Ingestion time — 10-page PDF fully queryable < 60s; failure threshold > 120s
NFR4: RAGAS faithfulness baseline > 0.7; auto-flag threshold < 0.6 triggers regression alert
NFR5: All data in transit encrypted via TLS 1.2+
NFR6: All data at rest encrypted using AWS-managed encryption (S3, DynamoDB, RDS)
NFR7: API keys stored in MongoDB — never logged in plaintext, never returned after initial issuance
NFR8: All provider credentials read from AWS Secrets Manager at operation time — never cached at startup; rotation takes effect on next request
NFR9: PII scrubbed from document content at ingestion and from query text at query time — zero tolerance for PII reaching vector store or LLM
NFR10: Namespace isolation enforced at the vector store query level — zero tolerance for cross-namespace results (critical failure, not degraded state)
NFR11: Audit log entries stored in DynamoDB — query text never written, API key hash only
NFR12: No secrets in code, configuration files, or environment variables
NFR13: Query path availability target: 99.5% (≈ 44 hours downtime per year)
NFR14: Ingestion path availability: best-effort with 3 retries (exponential backoff) and DLQ on exhaustion
NFR15: Transient dependency failures surface HTTP 503 Service Unavailable — no silent degraded results
NFR16: Ingestion job failures: update job status to `failed` with error reason; caller can re-trigger manually
NFR17: System supports 50 concurrent queries without degradation
NFR18: System supports up to 50 tenants and up to 20 agents per tenant (1,000 agents total)
NFR19: System supports up to 10,000 documents per agent and 10 concurrent ingestion jobs without blocking retrieval path
NFR20: Every significant architectural decision documented as an ADR in `docs/adrs/` before implementation begins
NFR21: Abstract interfaces (VectorStore, ChunkingStrategy, Reranker, EmbeddingProvider, LLMProvider) must remain stable — new implementations added without modifying existing interface contracts
NFR22: Each of the 12 build stages independently demonstrable — CI-CD pipeline includes RAGAS eval gate blocking deployments below threshold

### Additional Requirements

- No starter template — brownfield project built from the defined directory structure (`truerag/app/`, `truerag/tests/`, `truerag/terraform/`, etc.)
- Python 3.11+, FastAPI with async-first (asyncio) — all I/O-bound operations must be non-blocking; Uvicorn as ASGI server, Gunicorn as process manager on ECS Fargate
- Pydantic v2 for request/response validation and settings management (`pydantic-settings`)
- MongoDB Atlas (managed) for all tenant/agent config; `motor` async driver; all field names `snake_case`; timestamps always `created_at` / `updated_at`; IDs as `{entity}_id`
- AWS SQS standard queue for async ingestion (visibility timeout: 300s, max receive count: 3, DLQ retention: 14 days); message format includes `job_id`, `tenant_id`, `agent_id`, `document_id`, `s3_key`, `file_type`, `timestamp`
- AWS S3 for raw document archive before processing
- AWS DynamoDB — two separate tables: `truerag-audit-log` (partition: `tenant_id`, sort: `timestamp#query_hash`) and `truerag-ingestion-jobs` (partition: `job_id`)
- AWS ECS Fargate — two independent task definitions: `truerag-api` (FastAPI+Uvicorn+Gunicorn, scales on CPU/request count) and `truerag-worker` (SQS consumer, scales on queue depth); share no in-process state
- AWS Secrets Manager — all credentials read at operation time exclusively through `app/utils/secrets.py`; never cached at startup
- Terraform for all AWS infrastructure; single-region us-east-1 for v1
- GitHub Actions CI-CD with RAGAS eval gate in `deploy.yml` blocking deployments below threshold
- Five abstract interfaces with locked method signatures in `app/interfaces/`: `VectorStore` (upsert, query, delete_namespace, health), `ChunkingStrategy` (chunk), `Reranker` (rerank), `EmbeddingProvider` (embed), `LLMProvider` (generate)
- Central provider registry in `app/providers/registry.py` — maps config strings to concrete classes; all providers instantiated exclusively through registry via FastAPI `Depends()`
- Request-scoped config cache via FastAPI `Depends()` — config loaded once per request, passed through entire pipeline depth; updates take effect on next request; no TTL complexity
- Semantic cache as a dedicated pgvector table on same RDS instance, scoped by `agent_id`; TTL via `created_at` + periodic cleanup; avoids Redis as new infrastructure dependency
- In-process fixed window rate limiter per tenant per minute (Redis deferred to v2)
- Namespace format: `{tenant_id}_{agent_id}` — hard filter on every VectorStore query method; derived deterministically, never hardcoded inline
- Structured JSON logging format (timestamp, level, tenant_id, agent_id, request_id, operation, latency_ms, extra) via `app/utils/observability.py` exclusively; stdout → CloudWatch Logs via ECS awslogs driver
- Error response envelope: `{"error": {"code": "MACHINE_READABLE_CONSTANT", "message": "...", "request_id": "UUID"}}`; error codes as `ErrorCode` enum in `app/core/errors.py`; `request_id` generated at middleware entry
- Cursor-based pagination (base64-encoded MongoDB ObjectId) via `?cursor=` query param for all list endpoints
- `datetime.now(datetime.timezone.UTC)` exclusively — never `datetime.utcnow()` (deprecated Python 3.12)
- Typed exception hierarchy (`TrueRAGError`, `NamespaceViolationError`, `PIIDetectedError`, `ProviderUnavailableError`, `IngestionError`) mapped to HTTP responses by `app/core/exception_handlers.py`
- Retry logic implemented once as decorator in `app/utils/retry.py` (3 retries, exponential backoff) — never reimplemented per-provider
- PII scrubbing via Microsoft Presidio Analyzer; called explicitly at two points: pre-chunk (ingestion) and pre-retrieval (query) via `app/utils/pii.py`; not bypassable via middleware
- RAGAS evaluation is synchronous — `eval_service.py` must use `asyncio.get_event_loop().run_in_executor()` to avoid blocking the event loop
- Semantic cache invalidation: `ingestion_service.py` must call `semantic_cache.invalidate(agent_id)` explicitly at document ingestion completion AND document deletion
- Document versioning: hash-based deduplication; incoming document hash compared against existing records for the `agent_id`; version incremented on match; previous version archived
- FR42 regression alert path: `eval_service` writes custom metric to CloudWatch → CloudWatch alarm triggers → SNS notification (v1: email via Terraform-configured alarm; v2: Slack/webhook)
- ADR standard: one file per architectural decision in `docs/adrs/`; written before implementation begins
- Code quality: Ruff (lint + format), mypy (strict), pre-commit hooks enforcing both
- Dependency management: pip + `pyproject.toml`; runtime deps in `requirements.txt`, dev/test in `requirements-dev.txt`
- All API JSON fields `snake_case`; all routes prefixed `/v1/`; multipart/form-data for document file upload; cursor-based pagination on all list endpoints
- `scripts/` utilities (seed_tenant.py, run_eval.py, reindex.py) access TrueRAG via REST API only — no direct DB access

### UX Design Requirements

N/A — No UX document exists. TrueRAG is an API-only product with no frontend UI in v1.

### FR Coverage Map

```
FR1:  Epic 2  — Register tenant with unique identifier
FR2:  Epic 2  — List all registered tenants
FR3:  Epic 2  — Delete tenant + all associated data
FR4:  Epic 2  — Issue API key on tenant registration
FR5:  Epic 2  — Create named RAG Agent with full pipeline config
FR6:  Epic 2  — Update agent config at runtime (no restart)
FR7:  Epic 2  — Retrieve agent current config and status
FR8:  Epic 2  — List all agents for a tenant
FR9:  Epic 2  — Delete agent and its namespace
FR10: Epic 2  — Warn on config change creating mismatch with existing ingested data
FR11: Epic 3  — Upload documents (PDF, TXT, MD, DOCX)
FR12: Epic 3  — Async upload; returns job ID immediately
FR13: Epic 3  — Poll ingestion status by job ID
FR14: Epic 3  — List all documents in an agent
FR15: Epic 4  — Delete document + all associated chunks from namespace
FR16: Epic 4  — Document versioning via hash deduplication
FR17: Epic 4  — Developer-triggered full reindex
FR18: Epic 3  — PII scrubbing pre-chunk at ingestion
FR19: Epic 3  — Archive raw documents to S3 before processing
FR20: Epic 4  — Chunk metadata (tenant, agent, doc, index, strategy, ts, version)
FR21: Epic 2 (config schema) / Epic 7 (semantic, hierarchical, doc-aware implementations)
FR22: Epic 2 (config schema) / Epic 8 (Cohere, Bedrock embedding providers)
FR23: Epic 2 (config schema) / Epic 8 (Qdrant, Pinecone backends)
FR24: Epic 2 (config schema) / Epic 7 (hybrid + sparse retrieval modes)
FR25: Epic 2 (config schema) / Epic 7 (cross-encoder + Cohere Rerank)
FR26: Epic 2  — top-k retrieval count per agent config
FR27: Epic 2 (config schema) / Epic 8 (OpenAI, Bedrock LLM providers)
FR28: Epic 4  — Namespace isolation enforced at vector store query level
FR29: Epic 5  — Metadata filters to scope retrieval within agent namespace
FR30: Epic 5  — Submit natural language query via REST API
FR31: Epic 5  — PII scrubbing pre-retrieval at query time
FR32: Epic 5  — Generated answer with citations
FR33: Epic 5  — Confidence score on every response
FR34: Epic 5  — Structured JSON output from query
FR35: Epic 7  — Optional query rewrite for improved recall
FR36: Epic 7  — Query routing (retrieval-needed vs. direct LLM)
FR37: Epic 8  — Semantic cache hit on similarity threshold, scoped per agent
FR38: Epic 8  — Semantic cache invalidation on document update
FR39: Epic 6  — Define + store golden dataset per agent
FR40: Epic 6  — Trigger RAGAS evaluation run
FR41: Epic 6  — Store experiment result (config snapshot + RAGAS scores)
FR42: Epic 6  — Auto regression alert when score drops below threshold
FR43: Epic 6  — View evaluation history and score trends
FR44: Epic 6  — Evaluation API triggerable by CI-CD
FR45: Epic 9  — Per-tenant/agent metrics: query volume, latency, cost
FR46: Epic 9  — Cost per query: tokens + embedding + reranker calls
FR47: Epic 9  — Per-stage latency: chunking, embedding, retrieval, reranking, generation
FR48: Epic 5  — Tamper-evident audit log entry per query event
FR49: Epic 1  — Health and readiness endpoints
FR50: Epic 1  — API key authentication on every request
FR51: Epic 1  — Cross-tenant access rejected at API boundary
FR52: Epic 1  — Per-tenant per-minute rate limiting
FR53: Epic 1  — Credentials from Secrets Manager at operation time
FR54: Epic 7  — Extension via abstract interface without modifying core logic
FR55: Epic 9  — Prometheus-compatible metrics endpoint
FR56: Epic 2  — Detect embedding model change; flag re-embedding required
FR57: Epic 3  — Return unique document ID on upload
```

## Epic List

### Epic 1: Platform Foundation & Security Baseline
AI Platform Engineers can deploy a running, observable, secure API skeleton — with authentication, rate limiting, secrets management, health endpoints, structured logging, and a semantic cache stub enabling forward-compatible call sites in later epics — that all future epics build upon.
**FRs covered:** FR49, FR50, FR51, FR52, FR53
**NFRs covered:** NFR5–12, NFR13, NFR15, NFR20
**Build stage:** 1

### Epic 2: Tenant & Agent Lifecycle Management
Tenant Developers can register their team, receive an API key, create named RAG Agents with a full pipeline configuration (all strategy and provider fields defined and validated upfront), update that configuration at runtime, and detect when a change requires a reindex — all without writing code.
**FRs covered:** FR1–10, FR21 (config schema), FR22 (config schema), FR23 (config schema), FR24 (config schema), FR25 (config schema), FR26, FR27 (config schema), FR56
**NFRs covered:** NFR7, NFR18
**Build stage:** 2

### Epic 3: Async Document Ingestion Pipeline
Tenant Developers can upload documents (PDF, TXT, MD, DOCX), receive an immediate job ID, track async processing through a queue, poll for status, and list documents — with PII scrubbing and S3 archiving applied before any processing begins.
**FRs covered:** FR11, FR12, FR13, FR14, FR18, FR19, FR57
**NFRs covered:** NFR3, NFR9, NFR14, NFR16, NFR19
**Build stage:** 3

### Epic 4: Chunking, Embedding & Vector Store Namespace Isolation
Tenant Developers can have their uploaded documents fully chunked (fixed-size), embedded (OpenAI), and indexed into a strictly isolated pgvector namespace — with chunk metadata, document versioning, deletion, and developer-triggered reindex all working end-to-end.
**FRs covered:** FR15, FR16, FR17, FR20, FR28
**NFRs covered:** NFR10, NFR19
**Build stage:** 4

### Epic 5: Query, Retrieval & Answer Generation (MVP)
Service Consumers can submit natural language queries and receive grounded answers with citations, confidence scores, metadata-filtered retrieval, and PII-scrubbed context — reliably within p95 latency targets — while every query event is audit-logged in DynamoDB.
**FRs covered:** FR29, FR30, FR31, FR32, FR33, FR34, FR48
**NFRs covered:** NFR1, NFR2, NFR10, NFR11, NFR13
**Build stage:** 5

### Epic 6: Evaluation, Quality Assurance & Regression Detection
Tenant Developers can define golden datasets, trigger RAGAS evaluation runs, compare experiments historically, and receive automatic regression alerts when quality drops — completing the MVP and enabling CI-CD quality gates.
**FRs covered:** FR39, FR40, FR41, FR42, FR43, FR44
**NFRs covered:** NFR4, NFR22
**Build stage:** 6

### Epic 7: Advanced Chunking, Retrieval Strategies & Extension Model
Tenant Developers can switch to semantic, hierarchical, or document-aware chunking, enable hybrid search and sparse retrieval, apply rerankers, and use query rewriting and routing — while AI Platform Engineers can add new backends via the abstract interface without touching core pipeline logic.
**FRs covered:** FR21 (full strategy set), FR24 (hybrid/sparse), FR25 (cross-encoder/Cohere Rerank), FR35, FR36, FR54
**NFRs covered:** NFR21
**Build stages:** 7–8

### Epic 8: Multi-Provider Expansion & Semantic Caching
Tenant Developers can choose from multiple embedding providers (Cohere, Bedrock), LLM providers (OpenAI, Bedrock), and vector store backends (Qdrant, Pinecone) — and benefit from per-agent semantic caching that returns near-instant results for repeated query patterns.
**FRs covered:** FR22 (Cohere/Bedrock), FR23 (Qdrant/Pinecone), FR27 (OpenAI/Bedrock LLMs), FR37, FR38
**NFRs covered:** NFR21
**Build stages:** 9–10

### Epic 9: Platform Observability & Governance
Platform Admins gain full visibility into per-tenant and per-agent metrics: query volume, per-stage latency, cost-per-query (tokens, embeddings, reranker calls) — exposed via a Prometheus-compatible metrics endpoint.
**FRs covered:** FR45, FR46, FR47, FR55
**NFRs covered:** NFR17
**Build stage:** 11

### Epic 10: Production Deployment & Operations
AI Platform Engineers can deploy TrueRAG to production AWS (ECS Fargate, RDS+pgvector, SQS+DLQ, S3, DynamoDB, Secrets Manager, CloudWatch alarms, VPC) via Terraform, with a full GitHub Actions CI-CD pipeline that blocks deployments below the RAGAS quality threshold.
**FRs covered:** (infrastructure delivery — all 57 FRs already delivered through Epics 1–9)
**NFRs covered:** NFR13–19, NFR22
**Build stage:** 12

<!-- Stories appended below by step-03-create-stories -->

## Epic 1: Platform Foundation & Security Baseline

AI Platform Engineers can deploy a running, observable, secure API skeleton — with authentication, rate limiting, secrets management, health endpoints, and structured logging — that all future epics build upon.

### Story 1.1: Project Scaffold & Application Skeleton

As an AI Platform Engineer,
I want a fully configured Python project scaffold with FastAPI app factory, directory structure, and code quality tooling,
So that all future implementation has a consistent, lintable, type-checkable foundation.

**Acceptance Criteria:**

**Given** a fresh clone of the repository
**When** `pip install -r requirements-dev.txt` is run
**Then** all dependencies install without error, Ruff linting passes with zero violations, and mypy strict type checking passes with zero errors

**Given** the FastAPI application is started with `uvicorn app.main:app`
**When** the process starts
**Then** the app starts without error, OpenAPI docs are available at `/docs` and `/redoc`, and all routes are prefixed `/v1/`

**Given** the project directory structure
**When** it is inspected
**Then** it matches the architecture spec exactly: `app/api/v1/`, `app/core/`, `app/models/`, `app/services/`, `app/pipelines/`, `app/interfaces/`, `app/providers/`, `app/workers/`, `app/utils/`, `tests/` (mirroring `app/`), `scripts/`, `terraform/`, `docs/adrs/`, `.github/workflows/`

**Given** a pre-commit configuration
**When** `git commit` is run
**Then** Ruff and mypy execute automatically and block the commit on any violation

---

### Story 1.2: Core Configuration & Structured Logging

As an AI Platform Engineer,
I want a typed settings system and structured JSON logger wired into the application,
So that all configuration is validated at startup and every log entry is a consistent, CloudWatch-queryable JSON object.

**Acceptance Criteria:**

**Given** `app/core/config.py` loaded by `pydantic-settings`
**When** the application starts
**Then** all required settings are type-validated; missing required settings cause a startup error with the setting name; no secrets appear in the settings class or `.env` files

**Given** a request enters the API
**When** any handler executes
**Then** a unique UUID v4 `request_id` is generated at middleware entry, injected into request context, and included in every log entry emitted during that request

**Given** the structured logger in `app/utils/observability.py`
**When** a log is emitted at any level
**Then** the output is a valid JSON object with fields `timestamp` (ISO 8601 UTC), `level`, `tenant_id`, `agent_id`, `request_id`, `operation`, `latency_ms`, `extra` — never plain text, never via `print()` or stdlib `logging` directly

---

### Story 1.3: Error Handling Infrastructure

As an AI Platform Engineer,
I want a centralised error system with typed exceptions, an `ErrorCode` enum, and a consistent error response envelope,
So that every API error returns a predictable `{"error": {"code": "...", "message": "...", "request_id": "..."}}` structure callers can rely on.

**Acceptance Criteria:**

**Given** `app/core/errors.py`
**When** inspected
**Then** it contains: `TrueRAGError` base exception with typed subclasses (`NamespaceViolationError`, `PIIDetectedError`, `ProviderUnavailableError`, `IngestionError`, `RateLimitError`); `ErrorCode` enum containing at minimum `AGENT_NOT_FOUND`, `NAMESPACE_VIOLATION`, `PII_DETECTED`, `CHUNKING_STRATEGY_MISMATCH`, `EMBEDDING_MODEL_MISMATCH`, `REINDEX_REQUIRED`, `RATE_LIMIT_EXCEEDED`; no error code is hardcoded as a raw string anywhere in the codebase

**Given** a `TrueRAGError` subclass is raised in any handler
**When** `app/core/exception_handlers.py` processes it
**Then** the response body is `{"error": {"code": "...", "message": "...", "request_id": "..."}}` with the appropriate HTTP status code; no FastAPI default `detail` field leaks through

**Given** `ProviderUnavailableError` is raised
**When** the exception handler processes it
**Then** the HTTP response is exactly 503 Service Unavailable with the error envelope

---

### Story 1.4: Database & External Service Connections with Health/Readiness Endpoints

As an AI Platform Engineer,
I want all database and AWS service clients established as FastAPI lifespan dependencies, with working health and readiness endpoints,
So that infrastructure monitoring can verify platform liveness and the availability of all five dependencies (FR49).

**Acceptance Criteria:**

**Given** the FastAPI app lifespan
**When** the application starts
**Then** a `motor` MongoDB client, `asyncpg` pgvector connection pool, and `aioboto3` sessions for SQS, S3, DynamoDB, and Secrets Manager are all initialised; failure to connect to any critical dependency raises a startup error naming the failing dependency

**Given** `GET /v1/health`
**When** called at any time
**Then** it returns HTTP 200 with `{"status": "ok"}` — this endpoint does not check dependencies; it confirms the process is alive

**Given** `GET /v1/ready` when all dependencies are reachable
**When** the endpoint responds
**Then** it returns HTTP 200 with a JSON body showing the status of all five dependencies: MongoDB, pgvector, SQS, DynamoDB, and S3

**Given** `GET /v1/ready` when any dependency is unreachable
**When** the endpoint responds
**Then** it returns HTTP 503 with the error envelope identifying the failing dependency and the `request_id`

---

### Story 1.5: Secrets Management, Retry Decorator & PII Scrubbing Utility

As an AI Platform Engineer,
I want an AWS Secrets Manager wrapper, an exponential backoff retry decorator, and a PII scrubbing utility available to all pipelines,
So that credential access is centralised (FR53), retry logic is never duplicated per provider, and PII scrubbing is a single explicit call site for both the ingestion and query pipelines.

**Acceptance Criteria:**

**Given** `app/utils/secrets.py`
**When** any application code needs a credential
**Then** it calls `await get_secret(name)` from this module only; no other file imports `aioboto3` directly for Secrets Manager; the secret is read at call time, never cached at startup

**Given** `app/utils/retry.py` with `@retry(max_attempts=3, backoff_factor=2)` applied to an async function
**When** the decorated function raises an exception
**Then** it retries up to 3 times with exponential backoff (1s, 2s, 4s); it raises the last exception on exhaustion; no provider file reimplements retry logic inline

**Given** `app/utils/pii.py` calling Microsoft Presidio Analyzer
**When** `scrub_pii(text: str) -> str` is called with text containing a name, email, or phone number
**Then** those entities are replaced with anonymised placeholders; the original sensitive text is never returned

**Given** `scrub_pii()` called with text containing no PII
**When** the function executes
**Then** the original text is returned unchanged

---

### Story 1.6: API Key Authentication & Cross-Tenant Access Control

As an AI Platform Engineer,
I want every request authenticated via `X-API-Key` header with tenant resolution from MongoDB, and cross-tenant access rejected at the API boundary,
So that only legitimate tenants access their own resources and no business logic runs for unauthenticated or unauthorised requests (FR50, FR51).

**Acceptance Criteria:**

**Given** a request with a valid `X-API-Key` header
**When** `app/core/auth.py` middleware processes it
**Then** the tenant is resolved from MongoDB by comparing `SHA-256(raw_key)` against `api_key_hash`; the resolved tenant object is injected into request state; the raw key is never logged

**Given** a request with a missing or invalid `X-API-Key`
**When** the auth middleware processes it
**Then** HTTP 401 Unauthorized is returned with the error envelope before any handler executes; no MongoDB queries for agents or documents occur

**Given** a valid API key for Tenant A attempting to access a resource belonging to Tenant B
**When** the access control check runs
**Then** HTTP 403 Forbidden is returned with `ErrorCode.NAMESPACE_VIOLATION` before any retrieval or mutation logic executes

---

### Story 1.7: Per-Tenant Rate Limiting

As an AI Platform Engineer,
I want an in-process fixed-window rate limiter enforcing per-tenant per-minute request limits,
So that no single tenant exhausts platform resources and over-limit requests receive a clear 429 response (FR52).

**Acceptance Criteria:**

**Given** a tenant's request count is below their configured per-minute limit
**When** a request arrives
**Then** it passes through to the handler without restriction

**Given** a tenant configured with limit N requests per minute
**When** the (N+1)th request arrives within the same 1-minute window
**Then** HTTP 429 Too Many Requests is returned with the error envelope and `ErrorCode.RATE_LIMIT_EXCEEDED`; no business logic executes

**Given** a tenant with no explicit limit set in MongoDB
**When** a request arrives
**Then** the default limit from `app/core/config.py` is applied

**Given** the in-process counter behaviour
**When** documented in `docs/adrs/`
**Then** the ADR explicitly states that per-replica enforcement is the v1 behaviour and Redis-backed global enforcement is deferred to v2

---

### Story 1.8: Abstract Interfaces & Provider Registry

As an AI Platform Engineer,
I want all five abstract provider interfaces defined with locked method signatures and a central registry mapping config strings to concrete implementations, including a PassthroughReranker registered for `reranker: none`,
So that all future provider code is registered in one place, pipeline code can never instantiate providers directly, and the query pipeline works without reranking from day one (FR54, NFR21).

**Acceptance Criteria:**

**Given** `app/interfaces/` with five abstract base classes
**When** their method signatures are inspected
**Then** they exactly match the architecture spec: `VectorStore` (upsert, query, delete_namespace, health), `ChunkingStrategy` (chunk), `Reranker` (rerank), `EmbeddingProvider` (embed), `LLMProvider` (generate); no concrete implementations exist in this directory

**Given** `app/providers/registry.py`
**When** inspected
**Then** it contains five registry dicts (`VECTOR_STORE_REGISTRY`, `CHUNKING_REGISTRY`, `RERANKER_REGISTRY`, `EMBEDDING_REGISTRY`, `LLM_REGISTRY`) mapping config string values to concrete classes; adding a new provider requires only a new entry in this file

**Given** `reranker: none` in an agent config
**When** the registry resolves the reranker for that agent
**Then** a `PassthroughReranker` instance from `app/providers/rerankers/passthrough.py` is returned; calling `rerank(query, chunks, top_k)` on it returns the input chunks unchanged in their original order

**Given** `app/core/dependencies.py` FastAPI `Depends()` functions
**When** they resolve provider instances
**Then** they look up the agent config string in the appropriate registry and return the instance; no service or pipeline file instantiates concrete provider classes directly

**Given** mypy strict type checking runs on `app/interfaces/` and `app/providers/`
**When** the check completes
**Then** all abstract method signatures are satisfied by registered implementations and no type errors are reported

---

### Story 1.9: Semantic Cache Stub

As an AI Platform Engineer,
I want a `semantic_cache.py` module with a no-op `invalidate(agent_id)` method available from the start of the project,
So that Stories 4.6 (reindex) and 6.1 (golden dataset) can call cache invalidation without forward-coupling to Epic 8, and the real implementation in Epic 8 is a drop-in replacement with no changes to call sites.

**Acceptance Criteria:**

**Given** `app/utils/semantic_cache.py` exists after Epic 1 is complete
**When** its interface is inspected
**Then** it exposes at minimum `async def invalidate(agent_id: str) -> None` — calling this method is a silent no-op; it does not raise, does not write to any store, and does not log

**Given** `app/utils/semantic_cache.py` is imported and called by `ingestion_service.py` or `eval_service.py` before Epic 8 is implemented
**When** `invalidate(agent_id)` is called
**Then** the call completes without error and has no side effects; no conditional `if semantic_cache_enabled` guard is needed at the call site

**Given** Epic 8 implements real semantic cache functionality
**When** `app/utils/semantic_cache.py` is updated to a real implementation
**Then** all existing call sites in Stories 4.6 and 6.1 continue to work without modification — the stub and real implementation share the same method signature

**Given** mypy strict type checking runs on `app/utils/semantic_cache.py`
**When** the check completes
**Then** the module passes with zero errors; the stub is fully typed

---

## Epic 2: Tenant & Agent Lifecycle Management

Tenant Developers can register their team, receive an API key, create named RAG Agents with a full pipeline configuration (all strategy and provider fields defined and validated upfront), update that configuration at runtime, and detect when a change requires a reindex — all without writing code.

### Story 2.1: Tenant Registration & API Key Issuance

As a Tenant Developer,
I want to register my team as a tenant and receive an API key,
So that my team has an isolated identity on the platform and can authenticate all subsequent API calls.

**Acceptance Criteria:**

**Given** a `POST /v1/tenants` request with a unique tenant name
**When** the request is processed
**Then** a new tenant document is created in the `tenants` MongoDB collection with `tenant_id`, `name`, `api_key_hash` (SHA-256 of the generated key), `rate_limit_rpm` (default), `created_at`; the raw API key is returned once in the response and never stored; HTTP 201 is returned

**Given** a `POST /v1/tenants` request with a tenant name that already exists
**When** the request is processed
**Then** HTTP 409 Conflict is returned with the error envelope; no duplicate tenant document is created

**Given** a successful tenant registration
**When** the returned API key is used in an `X-API-Key` header on a subsequent request
**Then** the auth middleware resolves the tenant correctly via SHA-256 hash comparison against MongoDB

---

### Story 2.2: Tenant Listing & Deletion

As a Platform Admin,
I want to list all registered tenants and delete a tenant with all its associated data,
So that I can govern which teams are active on the platform (FR2, FR3).

**Acceptance Criteria:**

**Given** `GET /v1/tenants` with a valid API key
**When** the request is processed
**Then** it returns a paginated list `{"items": [...], "next_cursor": "..."}` of tenant records (excluding `api_key_hash`); cursor-based pagination applies; an empty platform returns `{"items": [], "next_cursor": null}`

**Given** `DELETE /v1/tenants/{tenant_id}` for an existing tenant
**When** the request is processed
**Then** for each agent belonging to the tenant, `vector_store.delete_namespace({tenant_id}_{agent_id})` is called to remove all vectors; all agent documents for the tenant are then deleted from MongoDB; the tenant document is deleted from MongoDB; HTTP 204 No Content is returned only after all deletions complete — no orphaned vector namespaces remain

**Given** `DELETE /v1/tenants/{tenant_id}` for a non-existent tenant
**When** the request is processed
**Then** HTTP 404 Not Found is returned with the error envelope

---

### Story 2.3: RAG Agent Creation with Full Pipeline Configuration

As a Tenant Developer,
I want to create a named RAG Agent with a complete pipeline configuration specifying chunking strategy, vector store, embedding provider, LLM provider, retrieval mode, reranker, and top-k,
So that my agent's retrieval pipeline is fully defined from day one and all config fields are validated against supported values (FR5, FR21–27).

**Acceptance Criteria:**

**Given** `POST /v1/agents` with a valid config block (name, chunking_strategy, vector_store, embedding_provider, llm_provider, retrieval_mode, reranker, top_k)
**When** the request is processed
**Then** an agent document is created in the `agents` MongoDB collection with all config fields, `agent_id`, `tenant_id`, `status: active`, `created_at`, `updated_at`; HTTP 201 is returned with the full agent object

**Given** a config block with an unsupported value for any field (e.g. `chunking_strategy: unknown`)
**When** the request is processed
**Then** HTTP 400 Bad Request is returned listing the invalid field and the supported values; no agent document is created

**Given** a `POST /v1/agents` request with a name already used by the same tenant
**When** the request is processed
**Then** HTTP 409 Conflict is returned; no duplicate agent is created

**Given** a tenant attempts to create an agent using another tenant's `tenant_id`
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; no agent is created

---

### Story 2.4: Agent Retrieval & Listing

As a Tenant Developer,
I want to retrieve an individual agent's configuration and list all agents under my tenant,
So that I can inspect the current pipeline config and see what agents my team has registered (FR7, FR8).

**Acceptance Criteria:**

**Given** `GET /v1/agents/{agent_id}` for an agent belonging to the calling tenant
**When** the request is processed
**Then** the full agent config document is returned with all pipeline fields and `status`; HTTP 200 is returned

**Given** `GET /v1/agents/{agent_id}` for an agent belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned with the error envelope; the agent data is not exposed

**Given** `GET /v1/agents/{agent_id}` for a non-existent agent ID
**When** the request is processed
**Then** HTTP 404 Not Found is returned

**Given** `GET /v1/agents` for a tenant with multiple agents
**When** the request is processed
**Then** a paginated list `{"items": [...], "next_cursor": "..."}` of agent documents is returned for that tenant only; agents from other tenants are never included

---

### Story 2.5: Runtime Agent Config Update & Mismatch Detection

As a Tenant Developer,
I want to update my agent's pipeline configuration at runtime without restarting the service, and receive a clear warning when my change creates a mismatch with already-ingested data,
So that I can iterate on retrieval strategy with zero downtime and understand when a reindex is required (FR6, FR10, FR56).

**Acceptance Criteria:**

**Given** `PATCH /v1/agents/{agent_id}/config` with one or more valid config field changes
**When** the request is processed
**Then** the agent document in MongoDB is updated with the new values and `updated_at` timestamp; HTTP 200 is returned with the updated agent object; the change takes effect on the next request without any service restart

**Given** a `PATCH` request that changes `chunking_strategy` when the agent has existing ingested documents
**When** the request is processed
**Then** the update is applied and the response includes a warning: `"chunking_strategy updated. Existing chunks were generated with '<old_strategy>'. Re-ingestion required for changes to take effect."` (HTTP 200, not an error)

**Given** a `PATCH` request that changes `embedding_provider` when the agent has existing ingested documents
**When** the request is processed
**Then** the update is applied and the response includes a warning that existing chunks require re-embedding before retrieval quality is reliable (FR56); the warning names the old and new embedding providers

**Given** a `PATCH` request with an unsupported config value
**When** the request is processed
**Then** HTTP 400 Bad Request is returned; the agent document is not modified

---

### Story 2.6: Agent Deletion

As a Tenant Developer,
I want to delete a RAG Agent and its isolated namespace synchronously,
So that the agent and all its associated resources are fully removed in a single operation with no orphaned data (FR9).

**Acceptance Criteria:**

**Given** `DELETE /v1/agents/{agent_id}` for an agent belonging to the calling tenant
**When** the request is processed
**Then** the agent document is deleted from MongoDB and `vector_store.delete_namespace({tenant_id}_{agent_id})` is called synchronously — HTTP 204 is returned only after both operations complete

**Given** `DELETE /v1/agents/{agent_id}` for an agent that has ingested documents
**When** the request is processed
**Then** all document records for that agent are also deleted from MongoDB alongside the agent document and the vector store namespace — no orphaned document records remain

**Given** `DELETE /v1/agents/{agent_id}` for an agent belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; no deletion occurs

**Given** `DELETE /v1/agents/{agent_id}` for a non-existent agent
**When** the request is processed
**Then** HTTP 404 Not Found is returned

---

## Epic 3: Async Document Ingestion Pipeline

Tenant Developers can upload documents (PDF, TXT, MD, DOCX), receive an immediate job ID, track async processing through a queue, poll for status, and list documents — with PII scrubbing and S3 archiving applied before any processing begins.

### Story 3.1: Document Upload — S3 Archive & SQS Enqueue

As a Tenant Developer,
I want to upload a document to my agent's knowledge base and receive a job ID immediately,
So that I can submit documents for processing without waiting for the pipeline to complete (FR11, FR12, FR19, FR57).

**Acceptance Criteria:**

**Given** `POST /v1/agents/{agent_id}/documents` with a valid PDF, TXT, MD, or DOCX file (multipart/form-data)
**When** the request is processed
**Then** the raw file is archived to S3 at key `{tenant_id}/{agent_id}/{document_id}/{filename}` before any processing begins; a document record is created in MongoDB with `document_id`, `agent_id`, `tenant_id`, `filename`, `file_type`, `s3_key`, `status: queued`, `created_at`; a job record is created in the `truerag-ingestion-jobs` DynamoDB table with `job_id`, `document_id`, `status: queued`; an SQS message is enqueued with the job payload (job_id, tenant_id, agent_id, document_id, s3_key, file_type, timestamp); HTTP 202 Accepted is returned with `{"job_id": "...", "document_id": "...", "status": "queued"}`

**Given** a document upload for an agent belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; no S3 upload, MongoDB write, or SQS message occurs

**Given** a document upload with an unsupported file type (e.g. `.xlsx`)
**When** the request is processed
**Then** HTTP 400 Bad Request is returned; no S3 upload or SQS message occurs

**Given** S3 archiving succeeds but SQS enqueue fails
**When** the request is processed
**Then** the MongoDB document record status is set to `failed` with an error reason; the DynamoDB job record status is also set to `failed`; HTTP 500 is returned; the S3 object is retained for manual recovery

---

### Story 3.2: SQS Consumer Worker & Ingestion Job Status Tracking

As a Tenant Developer,
I want the SQS worker to process enqueued documents and update job status at each stage,
So that the ingestion pipeline runs asynchronously without blocking the API, and I can observe what stage my document is at (FR12, NFR14, NFR16).

**Acceptance Criteria:**

**Given** an SQS message is dequeued by the `truerag-worker` ECS task
**When** processing begins
**Then** both the MongoDB document record and the DynamoDB `truerag-ingestion-jobs` record are updated to `status: processing`; the SQS message is not deleted until processing fully completes

**Given** a transient failure during processing (e.g. S3 read timeout, embedding API timeout)
**When** the worker encounters the error
**Then** the SQS message becomes visible again after the visibility timeout (300s); up to 3 delivery attempts are made; on the 3rd failure the message is moved to the DLQ and both the MongoDB document record and the DynamoDB job record are updated to `status: failed` with the error reason

**Given** a permanent failure (e.g. corrupt file, unsupported content)
**When** the worker detects it
**Then** both the MongoDB document record and the DynamoDB job record are immediately updated to `status: failed` with a descriptive error reason; the SQS message is deleted (not retried); no partial chunks are stored

**Given** the worker processes a document successfully
**When** processing completes
**Then** both the MongoDB document record and the DynamoDB job record are updated to `status: ready`; the SQS message is deleted

---

### Story 3.3: Ingestion Status Polling & Document Listing

As a Tenant Developer,
I want to poll the ingestion status of a document by job ID and list all documents in my agent,
So that I know when a document is queryable and can manage my agent's knowledge base (FR13, FR14).

**Acceptance Criteria:**

**Given** `GET /v1/agents/{agent_id}/documents/{document_id}/status` for an in-progress document
**When** the request is processed
**Then** HTTP 200 is returned with `{"document_id": "...", "status": "queued|processing|ready|failed", "error_reason": null|"..."}` read from the DynamoDB `truerag-ingestion-jobs` table

**Given** polling for a document belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; the status is not exposed

**Given** `GET /v1/agents/{agent_id}/documents` for an agent with multiple documents
**When** the request is processed
**Then** a paginated list of document records is returned from MongoDB for that agent only, including `document_id`, `filename`, `file_type`, `status`, `created_at`; cursor-based pagination applies

---

### Story 3.4: PII Scrubbing at Ingestion

As a Tenant Developer,
I want PII automatically removed from every document before any chunk is stored,
So that no personal data reaches the vector store or LLM context, enforcing zero-tolerance compliance (FR18, NFR9).

**Acceptance Criteria:**

**Given** a document containing names, email addresses, or phone numbers is being processed by the ingestion worker
**When** `scrub_pii()` is called on the extracted raw text before chunking begins
**Then** all detected PII entities are replaced with anonymised placeholders; the scrubbed text — never the original — is passed to the chunking step

**Given** `scrub_pii()` is called during ingestion
**When** the call site is inspected
**Then** it is an explicit call in `app/pipelines/ingestion/pipeline.py` between the parse step and the chunk step; it is not applied via middleware or decorator that could be bypassed

**Given** PII scrubbing runs on a document
**When** a structured log entry is emitted for the scrubbing step
**Then** the log includes `operation: pii_scrub`, `tenant_id`, `agent_id`, `document_id`, and `latency_ms`; the original or scrubbed text content is never written to any log

---

## Epic 4: Chunking, Embedding & Vector Store Namespace Isolation

Tenant Developers can have their uploaded documents fully chunked (fixed-size), embedded (OpenAI), and indexed into a strictly isolated pgvector namespace — with chunk metadata, document versioning, deletion, and developer-triggered reindex all working end-to-end.

### Story 4.1: Document Parsing & Fixed-Size Chunking

As a Tenant Developer,
I want uploaded documents to be parsed into plain text and split into fixed-size chunks with configurable overlap,
So that document content is broken into retrievable units that the embedding step can process (FR20).

**Acceptance Criteria:**

**Given** the ingestion worker reads a document from S3
**When** `app/pipelines/ingestion/parser.py` processes it
**Then** PDF, TXT, MD, and DOCX files are each parsed to plain text; a `ParseError` is raised for corrupt or unreadable files; no parsing logic exists outside this module

**Given** an agent configured with `chunking_strategy: fixed_size`
**When** `FixedSizeChunker.chunk(text, metadata)` is called
**Then** the text is split into chunks of the configured token size with overlap; each returned `Chunk` carries metadata: `tenant_id`, `agent_id`, `document_id`, `chunk_index`, `chunking_strategy: fixed_size`, `timestamp`, `version`; no chunk exceeds the configured token size

**Given** `FixedSizeChunker` is instantiated
**When** the registry resolves the chunker
**Then** it is resolved through `CHUNKING_REGISTRY["fixed_size"]` via `Depends()` — never instantiated directly in the pipeline

---

### Story 4.2: OpenAI Embedding Generation

As a Tenant Developer,
I want each chunk embedded into a dense vector using the OpenAI embeddings API,
So that chunks are represented as vectors ready for similarity search in the vector store.

**Acceptance Criteria:**

**Given** an agent configured with `embedding_provider: openai`
**When** `OpenAIEmbedder.embed(texts)` is called with a list of chunk texts
**Then** the OpenAI embeddings API is called; a list of float vectors of consistent dimension is returned, one per input text; the API key is read from AWS Secrets Manager via `secrets.py` at call time — never from an environment variable or cached value

**Given** the OpenAI API call fails with a transient error (rate limit, timeout)
**When** the retry decorator handles it
**Then** the call is retried up to 3 times with exponential backoff via `@retry` from `app/utils/retry.py`; on exhaustion `ProviderUnavailableError` is raised

**Given** `OpenAIEmbedder` is instantiated
**When** the registry resolves the embedder
**Then** it is resolved through `EMBEDDING_REGISTRY["openai"]` — never directly instantiated in the pipeline

---

### Story 4.3: pgvector Upsert with Namespace Isolation

As a Tenant Developer,
I want embedded chunks stored in pgvector under a strictly isolated namespace per agent,
So that no agent's retrieval can ever access another agent's documents (FR28, NFR10).

**Acceptance Criteria:**

**Given** an agent configured with `vector_store: pgvector`
**When** `PgVectorStore.upsert(namespace, vectors)` is called after embedding
**Then** all vectors are inserted into the pgvector table under namespace `{tenant_id}_{agent_id}`; the namespace is derived from the agent config — never hardcoded inline; the DynamoDB job record and MongoDB document record are both updated to `status: ready` after a successful upsert

**Given** a `PgVectorStore.query()` call
**When** it executes
**Then** the namespace `{tenant_id}_{agent_id}` is applied as a hard filter on every query — it is not an optional parameter; a query for Agent A cannot return vectors belonging to Agent B under any condition

**Given** a cross-namespace result is returned by the vector store
**When** the retrieval path detects it
**Then** `NamespaceViolationError` is raised immediately; the result is not returned to the caller; the violation is logged as a critical error with `tenant_id`, `agent_id`, and `request_id`

**Given** `PgVectorStore` is instantiated
**When** the registry resolves the vector store
**Then** it is resolved through `VECTOR_STORE_REGISTRY["pgvector"]` — never directly instantiated in the pipeline

---

### Story 4.4: Document Deletion with Chunk Cleanup

As a Tenant Developer,
I want to delete a specific document and all its associated chunks from my agent's namespace,
So that stale or unwanted documents are fully removed from the knowledge base with no residual vectors (FR15).

**Acceptance Criteria:**

**Given** `DELETE /v1/agents/{agent_id}/documents/{document_id}` for a document belonging to the calling tenant's agent
**When** the request is processed
**Then** all vectors for that `document_id` are deleted from the pgvector namespace; the MongoDB document record is deleted; both the MongoDB and DynamoDB status records are removed; HTTP 204 No Content is returned only after all deletions complete

**Given** deletion of a document belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; no deletion occurs

**Given** deletion of a non-existent document ID
**When** the request is processed
**Then** HTTP 404 Not Found is returned

---

### Story 4.5: Document Versioning via Hash Deduplication

As a Tenant Developer,
I want re-uploading an existing document to create a new version with the old chunks removed,
So that I can update knowledge base content without accumulating stale vectors across versions (FR16).

**Acceptance Criteria:**

**Given** a document is uploaded whose content hash matches an existing document for the same agent
**When** `ingestion_service.py` processes the upload
**Then** a new document record is created with `version` incremented by 1; the previous version's chunks are deleted from the pgvector namespace; the previous version's MongoDB document record is marked `archived` with its metadata preserved for audit; the new version's chunks are stored in the pgvector namespace

**Given** a document is uploaded whose content hash does not match any existing document for the agent
**When** the upload is processed
**Then** a new document record is created with `version: 1`; no existing records are modified

**Given** a document record in MongoDB
**When** it is inspected
**Then** it contains a `version` integer field and a `content_hash` field; all version history for a document is queryable by `document_id` including archived records

---

### Story 4.6: Developer-Triggered Full Reindex

As a Tenant Developer,
I want to trigger a full reindex of all documents in my agent after a pipeline configuration change, with the semantic cache cleared first,
So that existing chunks are regenerated with the new strategy and no stale cached responses are served from the rebuilt knowledge base (FR17).

**Acceptance Criteria:**

**Given** `POST /v1/agents/{agent_id}/reindex` for an agent with ingested documents
**When** the request is processed
**Then** all existing chunks for the agent are deleted from the pgvector namespace; all `ready` documents are re-enqueued to SQS for re-processing through the full ingestion pipeline with the current agent config; HTTP 202 Accepted is returned with a count of documents re-enqueued

**Given** a reindex is triggered for an agent
**When** the reindex begins
**Then** `semantic_cache.invalidate(agent_id)` from `app/utils/semantic_cache.py` is called before any re-enqueueing occurs; prior to Epic 8 this is a no-op stub (Story 1.9); from Epic 8 onwards it clears cached responses — call sites are identical in both cases

**Given** the reindex is triggered
**When** document status records are updated
**Then** all affected MongoDB document records and DynamoDB job records are reset to `status: queued` before enqueueing begins

**Given** `POST /v1/agents/{agent_id}/reindex` for an agent belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; no reindex occurs

---

## Epic 5: Query, Retrieval & Answer Generation (MVP)

Service Consumers can submit natural language queries and receive grounded answers with citations, confidence scores, and PII-scrubbed context — reliably within p95 latency targets — while every query event is audit-logged.

### Story 5.1: Query Endpoint & PII Scrubbing

As a Service Consumer,
I want to submit a natural language query to a RAG Agent via REST and have PII stripped from my query before it reaches the retrieval pipeline,
So that my query is processed safely without sensitive data reaching the vector store or LLM (FR30, FR31).

**Acceptance Criteria:**

**Given** `POST /v1/agents/{agent_id}/query` with `{"query": "string", "top_k": integer (optional)}`
**When** the request is processed
**Then** the query is accepted; if `top_k` is omitted the agent's configured default is used; HTTP processing continues to the query pipeline

**Given** a query containing PII (name, email, phone number)
**When** `scrub_pii()` is called in `app/pipelines/query/pipeline.py` before retrieval
**Then** PII entities are replaced with placeholders; the scrubbed query — never the original — is passed to the vector store; the original query text is never written to any log or the audit log

**Given** the `scrub_pii()` call site in the query pipeline
**When** inspected
**Then** it is an explicit call between query receipt and vector store query — not applied via middleware or decorator that could be bypassed

**Given** a query to an agent belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; no retrieval occurs

---

### Story 5.2: Dense Vector Retrieval with Metadata Filtering

As a Service Consumer,
I want my query to retrieve the most relevant chunks from the agent's pgvector namespace using dense similarity search, with optional metadata filters,
So that retrieval is scoped precisely to the relevant documents and namespace (FR28, FR29).

**Acceptance Criteria:**

**Given** a query against an agent with `retrieval_mode: dense` and indexed documents
**When** `PgVectorStore.query(namespace, vector, top_k, filters)` is called
**Then** the top-k most similar chunks are returned from the agent's namespace only; the namespace `{tenant_id}_{agent_id}` is applied as a hard filter on every query regardless of other parameters

**Given** a query with optional metadata filters (e.g. `{"document_id": "..."}`)
**When** retrieval executes
**Then** only chunks matching both the namespace filter and the metadata filter are returned

**Given** a query returns chunks from the correct namespace
**When** the result set is inspected
**Then** every chunk carries its full metadata: `tenant_id`, `agent_id`, `document_id`, `chunk_index`, `chunking_strategy`, `version`

---

### Story 5.3: Answer Generation with Citations, Confidence Score & Structured Output

As a Service Consumer,
I want a generated answer with source citations, a confidence score, and optional structured JSON output returned for every query,
So that I can present grounded, verifiable answers to end users with full traceability back to source documents (FR32, FR33, FR34).

**Acceptance Criteria:**

**Given** retrieved chunks are passed to `app/pipelines/query/generator.py`
**When** `AnthropicLLMProvider.generate(prompt, context)` is called
**Then** the Anthropic API key is read from AWS Secrets Manager via `secrets.py` at call time; a generated answer string is returned; the provider is resolved through `LLM_REGISTRY["anthropic"]` — never directly instantiated

**Given** generation completes
**When** the query response is assembled
**Then** it contains `answer` (string), `confidence` (float 0.0–1.0 derived from retrieval similarity scores), `citations` (array of `{document_name, chunk_text, page_reference}`), `latency_ms` (integer); HTTP 200 is returned with this exact schema

**Given** a query request with `{"query": "...", "output_format": "json"}`
**When** generation completes
**Then** the `answer` field contains a valid JSON string rather than prose; the full response envelope structure (`answer`, `confidence`, `citations`, `latency_ms`) remains unchanged

**Given** `top_k` retrieved chunks
**When** citations are assembled
**Then** every citation references a chunk actually used in the generation context — no hallucinated citations; each citation includes `document_name`, `chunk_text`, and `page_reference`

**Given** the Anthropic API call fails with a transient error
**When** the retry decorator handles it
**Then** up to 3 retries with exponential backoff; on exhaustion `ProviderUnavailableError` is raised and HTTP 503 is returned to the caller

---

### Story 5.4: Query Audit Logging

As a Platform Admin,
I want every query event written to a tamper-evident audit log in DynamoDB as a non-blocking background task,
So that all retrieval activity is traceable by tenant, agent, and time without adding to query response latency or exposing query content (FR48, NFR11).

**Acceptance Criteria:**

**Given** a query is processed successfully or returns an error
**When** `query_service.py` completes the request
**Then** an audit log entry is written to the `truerag-audit-log` DynamoDB table with: `tenant_id`, `agent_id`, `api_key_hash` (SHA-256 of the caller's raw API key), `query_hash` (SHA-256 of the scrubbed query text), `timestamp` (ISO 8601 UTC), `response_confidence`, `cache_hit` (boolean, defaults to `false` — set to `true` when a semantic cache hit is returned)

**Given** the audit log write
**When** it is dispatched
**Then** it is performed as a FastAPI `BackgroundTask` so it never adds to query response latency even on slow DynamoDB writes; the HTTP response is returned to the caller before the write completes

**Given** the audit log entry
**When** inspected
**Then** it contains none of: query text, retrieved chunk text, generated answer, document content, or raw API key — only the fields listed above

**Given** the DynamoDB background write fails
**When** the background task handles it
**Then** the failure is logged as an error with `request_id`; the query response already returned to the caller is unaffected

---

### Story 5.5: End-to-End Query Latency Validation

As a Service Consumer,
I want query responses to consistently meet p95 latency targets under concurrent load so the API is reliable enough to power production UI integrations,
So that retrieval-as-a-service meets the latency SLA required by downstream products (NFR1, NFR2, NFR17).

**Acceptance Criteria:**

**Given** a query against an agent with indexed documents and `reranker: none`
**When** 50 concurrent queries are issued simultaneously using `locust` (defined in `scripts/locustfile.py`)
**Then** p95 end-to-end latency (retrieval + generation) is under 1.5 seconds; no single query exceeds 3 seconds; the locust run report is saved as `scripts/load_test_results/` and reviewed before the story is marked complete

**Given** per-stage latency tracking is wired into the query pipeline
**When** a query completes
**Then** a structured log entry is emitted with `operation: query_pipeline`, `latency_ms` (total), and per-stage breakdown fields (`retrieval_ms`, `generation_ms`) for each completed stage

**Given** a dependency (pgvector or Anthropic) is unavailable during a query
**When** `ProviderUnavailableError` is raised
**Then** HTTP 503 Service Unavailable is returned with the error envelope; no degraded or partial result is silently returned (NFR15)

---

## Epic 6: Evaluation, Quality Assurance & Regression Detection

Tenant Developers can define golden datasets, trigger RAGAS evaluation runs, compare experiments historically, and receive automatic regression alerts when quality drops — completing the MVP and enabling CI-CD quality gates.

### Story 6.1: Golden Dataset Management

As a Tenant Developer,
I want to define and store a golden dataset of question/answer pairs per agent,
So that I have a stable evaluation baseline to measure retrieval quality against (FR39).

**Acceptance Criteria:**

**Given** `POST /v1/agents/{agent_id}/eval` with a body containing a `questions` array of `{question, expected_answer}` pairs
**When** the request is processed
**Then** the golden dataset is stored in the `eval_datasets` MongoDB collection with `agent_id`, `tenant_id`, `questions[]`, `created_at`; HTTP 201 is returned with the dataset ID

**Given** an agent that already has a golden dataset
**When** a new dataset is uploaded
**Then** the existing dataset is replaced; `semantic_cache.invalidate(agent_id)` from `app/utils/semantic_cache.py` is called to ensure subsequent eval runs use fresh retrieval results; prior to Epic 8 this is a no-op stub (Story 1.9); from Epic 8 onwards it clears cached responses — call sites are identical in both cases

**Given** a golden dataset upload for an agent belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; no dataset is stored and no cache invalidation occurs

---

### Story 6.2: RAGAS Evaluation Run & Experiment Storage

As a Tenant Developer,
I want to trigger a RAGAS evaluation run against my agent's golden dataset and have the full result stored as an experiment,
So that I can measure faithfulness, answer relevance, context recall, and context precision against a known baseline (FR40, FR41).

**Acceptance Criteria:**

**Given** `POST /v1/agents/{agent_id}/eval/run` for an agent with a golden dataset of 20 or fewer questions
**When** the request is processed
**Then** a RAGAS evaluation runs synchronously; scores for faithfulness, answer relevance, context recall, and context precision are computed; the full experiment record is returned in the HTTP 200 response

**Given** `POST /v1/agents/{agent_id}/eval/run` for an agent with a golden dataset exceeding the configurable threshold (default: 20 questions)
**When** the request is processed
**Then** HTTP 202 Accepted is returned immediately with a `run_id`; the evaluation runs as a background task; the caller polls `GET /v1/agents/{agent_id}/eval/history` for the completed result identified by `run_id`

**Given** RAGAS evaluation executes (synchronous or background)
**When** `eval_service.py` calls it
**Then** the RAGAS library is called via `asyncio.get_event_loop().run_in_executor()` to avoid blocking the async event loop

**Given** the evaluation run completes
**When** results are stored
**Then** an experiment record is written to the `eval_experiments` MongoDB collection with: `agent_id`, `tenant_id`, `run_id`, `config_snapshot` (full agent config at time of run), `ragas_scores` (faithfulness, answer_relevance, context_recall, context_precision), `baseline_delta` (score change from previous run), `triggered_alert` (bool), `created_at`

**Given** an eval run for an agent with no golden dataset
**When** the request is processed
**Then** HTTP 422 Unprocessable Entity is returned with a clear error message; no eval run occurs

---

### Story 6.3: Regression Detection & Alert

As a Platform Admin,
I want automatic regression alerts pushed when an agent's RAGAS faithfulness score drops below its configured threshold,
So that quality degradation is surfaced immediately without manual monitoring (FR42, NFR4).

**Acceptance Criteria:**

**Given** an evaluation run completes and the faithfulness score is below the agent's configured baseline threshold (default 0.6)
**When** `eval_service.py` processes the result
**Then** a custom metric is written to CloudWatch with dimensions `tenant_id` and `agent_id`; the experiment record has `triggered_alert: true`; the CloudWatch alarm (configured in Terraform) triggers an SNS notification

**Given** an evaluation run completes with faithfulness score above the threshold
**When** the result is processed
**Then** no CloudWatch metric write occurs for the alarm; the experiment record has `triggered_alert: false`

**Given** the regression alert mechanism
**When** documented in `docs/adrs/`
**Then** the ADR explicitly states that v1 delivers email notification via Terraform-configured CloudWatch alarm + SNS; Slack/webhook push is deferred to v2

---

### Story 6.4: Evaluation History & CI-CD Integration

As a Platform Admin,
I want to view evaluation history and score trends per agent, and expose the eval endpoint for CI-CD pipeline integration,
So that quality trends are visible over time and deployments can be blocked on regression (FR43, FR44).

**Acceptance Criteria:**

**Given** `GET /v1/agents/{agent_id}/eval/history`
**When** the request is processed
**Then** a paginated list of experiment records is returned in descending `created_at` order, each including `run_id`, `ragas_scores`, `config_snapshot`, `baseline_delta`, `triggered_alert`, `created_at`; cursor-based pagination applies

**Given** a CI-CD pipeline calling `POST /v1/agents/{agent_id}/eval/run` with a valid API key
**When** the eval run completes (synchronous for datasets ≤20 questions)
**Then** the response includes the full RAGAS scores; the CI-CD pipeline can use the returned `faithfulness` score to fail the pipeline if below threshold — no special CI-CD mode is needed

**Given** eval history access for an agent belonging to a different tenant
**When** the request is processed
**Then** HTTP 403 Forbidden is returned; no experiment records are exposed

---

## Epic 7: Advanced Chunking, Retrieval Strategies & Extension Model

Tenant Developers can switch to semantic, hierarchical, or document-aware chunking, enable hybrid search and sparse retrieval, apply rerankers, and use query rewriting and routing — while AI Platform Engineers can add new backends via the abstract interface without touching core pipeline logic.

### Story 7.1: Semantic, Hierarchical & Document-Aware Chunking Strategies

As a Tenant Developer,
I want to configure semantic, hierarchical, or document-aware chunking for my agent,
So that I can improve retrieval quality by preserving meaning boundaries, parent context, or document structure (FR21).

**Acceptance Criteria:**

**Given** an agent configured with `chunking_strategy: semantic`
**When** `SemanticChunker.chunk(text, metadata)` is called
**Then** the text is split at meaning boundaries rather than fixed token counts; each chunk carries the full metadata schema (tenant_id, agent_id, document_id, chunk_index, chunking_strategy: semantic, timestamp, version)

**Given** an agent configured with `chunking_strategy: hierarchical`
**When** `HierarchicalChunker.chunk(text, metadata)` is called
**Then** small retrieval chunks are returned with a parent context reference embedded in metadata; the parent chunk text is stored and retrievable for context expansion at generation time

**Given** an agent configured with `chunking_strategy: document_aware`
**When** `DocumentAwareChunker.chunk(text, metadata)` is called
**Then** structural boundaries (headings, tables, sections) are detected and respected; chunks do not split across structural units where avoidable

**Given** all three new chunkers
**When** registered in `CHUNKING_REGISTRY`
**Then** they are available by config string (`semantic`, `hierarchical`, `document_aware`) with no changes to pipeline or service code; the backend-agnostic chunker test suite passes for all three implementations

---

### Story 7.2: Sparse Retrieval & Hybrid Search (BM25 + Dense + RRF)

As a Tenant Developer,
I want to configure hybrid search combining BM25 sparse retrieval with dense vector search merged via Reciprocal Rank Fusion,
So that retrieval quality improves for queries where keyword precision matters alongside semantic similarity (FR24).

**Acceptance Criteria:**

**Given** an agent configured with `retrieval_mode: sparse`
**When** a query is executed
**Then** BM25 keyword retrieval is performed against the agent's indexed chunks; results are returned ranked by BM25 score; no dense vector query is issued

**Given** BM25 sparse retrieval is performed
**When** the BM25 index is built
**Then** it is constructed at query time from the agent's chunk texts fetched from the vector store — no separate BM25 index store is maintained; this is a known performance tradeoff documented in an ADR in `docs/adrs/`

**Given** an agent configured with `retrieval_mode: hybrid`
**When** a query is executed
**Then** both BM25 sparse retrieval and dense vector retrieval are run in parallel; results are merged using Reciprocal Rank Fusion (RRF); the final ranked list is returned to the reranker or generator stage

**Given** `retrieval_mode` is changed from `dense` to `hybrid` via `PATCH /v1/agents/{agent_id}/config`
**When** the next query arrives
**Then** the new retrieval mode is active with no service restart; the config change takes effect on the next request via the request-scoped config cache

---

### Story 7.3: Reranking — Local Cross-Encoder & Cohere Rerank

As a Tenant Developer,
I want to configure a reranker to rescore a wider pool of retrieved chunks before generation,
So that the most relevant chunks surface to the top of the context window regardless of initial retrieval order, using the retrieve-wide-rerank-narrow pattern (FR25).

**Acceptance Criteria:**

**Given** a reranker is configured for an agent
**When** retrieval executes
**Then** the vector store retrieves `rerank_pool_size` candidates (default: 20, configurable per agent) before passing them to the reranker; the reranker reduces them to `top_k`; the reranker never receives fewer candidates than `top_k`

**Given** an agent configured with `reranker: cross_encoder`
**When** `CrossEncoderReranker.rerank(query, chunks, top_k)` is called with the candidate pool
**Then** the local cross-encoder model scores each (query, chunk) pair; chunks are returned in descending relevance score order, truncated to `top_k`; no external API call is made

**Given** an agent configured with `reranker: cohere`
**When** `CohereReranker.rerank(query, chunks, top_k)` is called with the candidate pool
**Then** the Cohere Rerank API is called with the query and chunk texts; the Cohere API key is read from AWS Secrets Manager via `secrets.py`; chunks are returned reranked by Cohere's relevance scores, truncated to `top_k`; transient failures are retried via `@retry`

**Given** both rerankers
**When** registered in `RERANKER_REGISTRY`
**Then** they are available by config string (`cross_encoder`, `cohere`) alongside the existing `none` (PassthroughReranker); switching rerankers requires only a config update — no pipeline code changes

---

### Story 7.4: Query Rewriting & Retrieval Routing

As a Tenant Developer,
I want optional query rewriting to expand queries for better recall, and automatic routing to skip retrieval for questions the LLM can answer directly,
So that retrieval quality improves for ambiguous queries and latency is reduced for direct-answer queries (FR35, FR36).

**Acceptance Criteria:**

**Given** an agent with `query_rewrite: true` in config
**When** a query arrives
**Then** `app/pipelines/query/rewriter.py` rewrites the query to improve retrieval recall before the vector store is queried; the rewritten query is used for retrieval; the original query is used for generation context

**Given** an agent with `query_rewrite: false` (default)
**When** a query arrives
**Then** `rewriter.py` is bypassed entirely; the original query is passed directly to retrieval

**Given** `app/pipelines/query/router.py` processes a query
**When** the router determines retrieval is not needed (query answerable from LLM knowledge directly)
**Then** the vector store is not queried; the LLM generates a response directly; the response includes `citations: []` and a `confidence` score indicating no retrieval was performed

**Given** the query routing decision
**When** logged
**Then** the structured log entry includes `operation: query_route`, `route: retrieval|direct`, `request_id`, `agent_id`, `tenant_id`

---

### Story 7.5: Extension Model Validation — New Backend via Abstract Interface

As an AI Platform Engineer,
I want to validate that adding a new provider backend requires only implementing the abstract interface and registering in the registry — with zero core pipeline changes,
So that the extension model is proven in practice, not just in design (FR54, NFR21).

**Acceptance Criteria:**

**Given** a new `ChunkingStrategy` implementation added in `app/providers/chunking/`
**When** it is registered in `CHUNKING_REGISTRY` with a new config string
**Then** an agent can be configured to use it with no changes to `app/pipelines/`, `app/services/`, or `app/api/`; the backend-agnostic test suite passes for the new implementation

**Given** all five abstract interfaces
**When** the codebase is statically analysed with mypy strict
**Then** every registered provider satisfies the full abstract interface contract; no `# type: ignore` annotations bypass the interface enforcement

**Given** an ADR for each new provider added in Stages 7–8
**When** the `docs/adrs/` directory is inspected
**Then** one ADR file exists per architectural decision introduced in this epic, written before the implementation was merged

---

## Epic 8: Multi-Provider Expansion & Semantic Caching

Tenant Developers can choose from multiple embedding providers (Cohere, Bedrock), LLM providers (OpenAI, Bedrock), and vector store backends (Qdrant, Pinecone) — and benefit from per-agent semantic caching that returns near-instant results for repeated query patterns.

### Story 8.1: Qdrant Vector Store Backend

As a Tenant Developer,
I want to configure my agent to use Qdrant Cloud as its vector store backend,
So that I can choose a purpose-built vector database for higher throughput workloads (FR23).

**Acceptance Criteria:**

**Given** an agent configured with `vector_store: qdrant`
**When** `QdrantVectorStore.upsert(namespace, vectors)` is called
**Then** vectors are stored in a Qdrant Cloud collection scoped to namespace `{tenant_id}_{agent_id}`; the Qdrant API key is read from AWS Secrets Manager via `secrets.py`

**Given** `QdrantVectorStore.query(namespace, vector, top_k, filters)`
**When** called
**Then** namespace is applied as a hard filter; cross-namespace results are never returned; `NamespaceViolationError` is raised if a cross-namespace result is detected

**Given** `QdrantVectorStore` registered in `VECTOR_STORE_REGISTRY["qdrant"]`
**When** the backend-agnostic vector store test suite runs against it
**Then** all assertions pass — the same test suite that validates `PgVectorStore` validates `QdrantVectorStore` with only the backend swapped

---

### Story 8.2: Pinecone Vector Store Backend

As a Tenant Developer,
I want to configure my agent to use Pinecone as its vector store backend,
So that I can use a managed, serverless vector store without operating any infrastructure (FR23).

**Acceptance Criteria:**

**Given** an agent configured with `vector_store: pinecone`
**When** `PineconeVectorStore.upsert(namespace, vectors)` is called
**Then** vectors are stored in a Pinecone index scoped to namespace `{tenant_id}_{agent_id}`; the Pinecone API key is read from AWS Secrets Manager via `secrets.py`

**Given** `PineconeVectorStore.query(namespace, vector, top_k, filters)`
**When** called
**Then** namespace is applied as a hard filter; cross-namespace results are never returned; the same namespace isolation guarantees as pgvector and Qdrant apply

**Given** `PineconeVectorStore` registered in `VECTOR_STORE_REGISTRY["pinecone"]`
**When** the backend-agnostic vector store test suite runs against it
**Then** all assertions pass with only the backend swapped

---

### Story 8.3: Cohere & AWS Bedrock Embedding Providers

As a Tenant Developer,
I want to configure my agent to use Cohere or AWS Bedrock for embeddings, with hard protection against serving degraded results after a provider switch,
So that I can choose the embedding provider that best fits my quality and cost requirements without risking silent dimension mismatch failures (FR22, FR56).

**Acceptance Criteria:**

**Given** an agent configured with `embedding_provider: cohere`
**When** `CohereEmbedder.embed(texts)` is called
**Then** the Cohere Embed API is called; a list of float vectors of consistent dimension is returned; the API key is read from Secrets Manager via `secrets.py`; transient failures retry via `@retry`

**Given** an agent configured with `embedding_provider: bedrock`
**When** `BedrockEmbedder.embed(texts)` is called
**Then** the AWS Bedrock embeddings API is called via `aioboto3`; AWS credentials are read from Secrets Manager; vectors of consistent dimension are returned

**Given** an agent switches `embedding_provider` when existing chunks are already indexed
**When** the first query executes before a reindex has been triggered
**Then** HTTP 422 Unprocessable Entity is returned with `ErrorCode.EMBEDDING_MODEL_MISMATCH` indicating the agent requires reindexing before queries can be served — degraded results from dimension-mismatched vectors are never silently returned

**Given** both new embedders registered in `EMBEDDING_REGISTRY`
**When** an agent switches `embedding_provider` via `PATCH /v1/agents/{agent_id}/config`
**Then** the mismatch warning from Story 2.5 fires (FR56) and the agent's query path blocks until a reindex completes

---

### Story 8.4: OpenAI & AWS Bedrock LLM Providers

As a Tenant Developer,
I want to configure my agent to use OpenAI GPT or AWS Bedrock as its LLM provider,
So that I can choose the generation model that best fits my quality, cost, and data residency requirements (FR27).

**Acceptance Criteria:**

**Given** an agent configured with `llm_provider: openai`
**When** `OpenAILLMProvider.generate(prompt, context)` is called
**Then** the OpenAI chat completions API is called; the API key is read from Secrets Manager via `secrets.py`; a generated answer string is returned; transient failures retry via `@retry`

**Given** an agent configured with `llm_provider: bedrock`
**When** `BedrockLLMProvider.generate(prompt, context)` is called
**Then** the AWS Bedrock inference API is called via `aioboto3`; AWS credentials are read from Secrets Manager; a generated answer string is returned

**Given** both new LLM providers registered in `LLM_REGISTRY`
**When** the backend-agnostic LLM provider test suite runs
**Then** all assertions pass with only the provider backend swapped

---

### Story 8.5: Semantic Cache — Lookup, Store, Invalidation & Audit Logging

As a Service Consumer,
I want repeated or near-identical queries served from a semantic cache with every cache hit still recorded in the audit log,
So that query latency and provider costs are reduced for common query patterns while the complete audit trail is preserved regardless of whether retrieval ran (FR37, FR38).

**Acceptance Criteria:**

**Given** a query arrives for an agent with `semantic_cache_enabled: true`
**When** `semantic_cache.lookup(agent_id, query_vector, threshold)` is called before retrieval
**Then** if a cached entry exists with cosine similarity above `semantic_cache_threshold` (configurable per agent), the cached response is returned immediately; the retrieval and generation pipeline is not executed; `latency_ms` reflects the cache hit time

**Given** a cache hit is returned
**When** the response is sent to the caller
**Then** an audit log entry is written to DynamoDB as a `BackgroundTask` with the standard fields (`tenant_id`, `agent_id`, `api_key_hash`, `query_hash`, `timestamp`, `response_confidence`) plus `cache_hit: true` — the audit log records every query event regardless of whether retrieval ran

**Given** a query that misses the semantic cache
**When** the full retrieval + generation pipeline completes
**Then** the response is stored in the `semantic_cache` pgvector table with `agent_id`, `query_vector`, `query_hash`, `response`, `created_at`; the namespace is scoped strictly by `agent_id`

**Given** a document is ingested or deleted for an agent
**When** `ingestion_service.py` completes the operation
**Then** `semantic_cache.invalidate(agent_id)` is called explicitly — all cache entries for that agent are deleted; this is a synchronous call before the ingestion status is marked `ready` (FR38)

**Given** the semantic cache table
**When** inspected
**Then** it is a dedicated pgvector table (`semantic_cache`) on the same RDS instance as document chunks — a separate table, not mixed with document vectors; TTL is enforced via `created_at` column with a periodic cleanup job

---

## Epic 9: Platform Observability & Governance

Platform Admins gain full visibility into per-tenant and per-agent metrics: query volume, per-stage latency, cost-per-query (tokens, embeddings, reranker calls) — exposed via a Prometheus-compatible metrics endpoint.

### Story 9.1: Per-Stage Latency Tracking

As a Platform Admin,
I want per-stage latency tracked and logged for every query and ingestion operation,
So that I can identify bottlenecks across the pipeline and verify p95 targets are being met (FR47).

**Acceptance Criteria:**

**Given** a query executes through the full pipeline
**When** each stage completes
**Then** a structured log entry is emitted per stage with `operation`, `latency_ms`, `tenant_id`, `agent_id`, `request_id` for stages: `pii_scrub`, `cache_lookup`, `retrieval`, `reranking`, `generation`, `audit_log_write`

**Given** an ingestion job processes through the worker pipeline
**When** each stage completes
**Then** a structured log entry is emitted per stage with `latency_ms` for stages: `parse`, `pii_scrub`, `chunk`, `embed`, `upsert`

**Given** per-stage latency instrumentation
**When** implemented
**Then** it uses the latency tracker from `app/utils/observability.py` consistently across both pipelines — no inline `time.time()` calls outside of this utility

---

### Story 9.2: Cost-Per-Query Tracking

As a Platform Admin,
I want the cost of every query tracked by component — token usage, embedding API calls, and reranker API calls — stored in a dedicated collection and aggregated per agent,
So that I can identify expensive agents and give teams accurate cost visibility (FR46).

**Acceptance Criteria:**

**Given** a query completes
**When** `query_service.py` assembles the response
**Then** a cost record is written to the `query_costs` MongoDB collection with: `tenant_id`, `agent_id`, `request_id`, `prompt_tokens`, `completion_tokens`, `embedding_calls`, `reranker_calls`, `timestamp`; cost records are never written to `eval_experiments`

**Given** a query that used an LLM provider
**When** the provider response is received
**Then** prompt token count and completion token count are captured from the provider response and written to the `query_costs` record for that `request_id`

**Given** a query that triggered an embedding API call (for the query vector)
**When** the embedding call completes
**Then** the number of embedding API calls is recorded in the `query_costs` record

**Given** a query that used a Cohere reranker
**When** reranking completes
**Then** the number of reranker API calls is recorded in the `query_costs` record

**Given** `GET /v1/metrics` is called
**When** cost aggregation runs
**Then** the response includes per-agent cost breakdown: total token usage (prompt + completion), total embedding API calls, total reranker API calls aggregated from the `query_costs` collection for the requested time window

---

### Story 9.3: Metrics Endpoint — Prometheus & Per-Tenant Aggregation

As a Platform Admin,
I want a metrics endpoint exposing per-tenant and per-agent query volume, latency, and cost in Prometheus-compatible format,
So that infrastructure monitoring tools can scrape TrueRAG metrics and platform admins have a single governance view (FR45, FR55).

**Acceptance Criteria:**

**Given** `GET /v1/metrics`
**When** called
**Then** the response body is valid Prometheus exposition format (text/plain; version=0.0.4) containing: `truerag_queries_total{tenant_id, agent_id}`, `truerag_query_latency_seconds{tenant_id, agent_id}` (histogram), `truerag_query_cost_tokens_total{tenant_id, agent_id}`, `truerag_ingestion_jobs_total{tenant_id, agent_id, status}`

**Given** a Prometheus scraper hitting `GET /v1/metrics`
**When** it scrapes
**Then** the endpoint returns within 500ms; metrics are aggregated from in-memory counters in the `truerag-api` process — not computed from raw MongoDB queries at scrape time

**Given** the `truerag-api` ECS task restarts
**When** metrics are scraped after restart
**Then** counters restart from zero for the current process lifetime; Prometheus handles counter resets natively via its `increase()` function; this reset-on-restart behaviour is documented in `docs/adrs/` as the v1 design decision — persistent counter storage is deferred to v2

**Given** ingestion job metrics (worker-side counts)
**When** exposed
**Then** they are derived from CloudWatch log metric filters on the `truerag-worker` structured logs — worker metrics are not served from the `truerag-api` in-memory counters; the `truerag_ingestion_jobs_total` metric in `GET /v1/metrics` reflects this source

**Given** `GET /v1/metrics` alongside `GET /v1/health` and `GET /v1/ready`
**When** all three are called
**Then** none require an `X-API-Key` header — they are unauthenticated infrastructure endpoints; metric labels expose only aggregate counts, never query content

---

## Epic 10: Production Deployment & Operations

AI Platform Engineers can deploy TrueRAG to production AWS (ECS Fargate, RDS+pgvector, SQS+DLQ, S3, DynamoDB, Secrets Manager, CloudWatch alarms, VPC) via Terraform, with a full GitHub Actions CI-CD pipeline that blocks deployments below the RAGAS quality threshold.

### Story 10.1: Terraform Infrastructure — Core AWS Services

As an AI Platform Engineer,
I want all core AWS infrastructure provisioned via Terraform so the entire platform can be created and destroyed reproducibly,
So that TrueRAG is deployable to production AWS with zero manual console steps (NFR13, NFR17–19).

**Acceptance Criteria:**

**Given** `terraform apply` in `terraform/environments/prod/`
**When** it completes
**Then** the following resources are provisioned: VPC with public/private subnets, RDS PostgreSQL with pgvector extension enabled, SQS standard queue + DLQ, S3 document archive bucket, DynamoDB `truerag-audit-log` table, DynamoDB `truerag-ingestion-jobs` table, AWS Secrets Manager entries (empty — values set out-of-band), MongoDB Atlas VPC peering connection to `us-east-1`, ECR repository named `truerag` with image scanning enabled and a lifecycle policy retaining the last 10 images

**Given** the Terraform configuration
**When** inspected
**Then** no secret values (API keys, passwords, connection strings) appear anywhere in `.tf` files, `tfvars`, or Terraform state; all secret values are populated in Secrets Manager out-of-band

**Given** `terraform/environments/dev/` and `terraform/environments/prod/`
**When** compared
**Then** they share modules from `terraform/modules/` with environment-specific variable overrides; no infrastructure logic is duplicated between environments

**Given** the Terraform configuration for data-at-rest encryption (NFR6)
**When** `terraform plan` is run
**Then** RDS instance has `storage_encrypted = true`; S3 bucket has `server_side_encryption_configuration` set to `AES256` or `aws:kms`; DynamoDB tables have `server_side_encryption` enabled; all three are verified in the `terraform/modules/` definitions and enforced by a `terraform validate` step in CI

**Given** the ALB and all API traffic (NFR5)
**When** the ALB listener is configured
**Then** the HTTPS listener on port 443 is the only listener forwarding to the `truerag-api` target group; the HTTP listener on port 80 redirects to HTTPS; TLS policy enforces a minimum of TLS 1.2

---

### Story 10.2: ECS Fargate Services — API & Worker Task Definitions

As an AI Platform Engineer,
I want the `truerag-api` and `truerag-worker` ECS Fargate services deployed as independent task definitions,
So that the API and ingestion worker scale independently and the async separation is enforced architecturally (NFR13, NFR14).

**Acceptance Criteria:**

**Given** `terraform/modules/ecs/`
**When** applied
**Then** two independent ECS services are created: `truerag-api` (FastAPI + Uvicorn + Gunicorn, scales on CPU/request count behind an ALB) and `truerag-worker` (SQS consumer, scales on SQS queue depth via Application Auto Scaling); the two services share no in-process state and run in separate task definitions

**Given** the `truerag-api` service
**When** it starts
**Then** the `GET /v1/ready` endpoint returns HTTP 200 before the ALB target group marks the task healthy and starts routing traffic

**Given** the `truerag-worker` service
**When** the SQS queue depth exceeds the configured threshold
**Then** Application Auto Scaling adds worker tasks; when queue depth returns to baseline, tasks scale back down; ingestion load never impacts the `truerag-api` CPU or memory

**Given** CloudWatch Logs configured via ECS `awslogs` log driver
**When** either service emits structured JSON log entries
**Then** they are streamed to CloudWatch Log Groups `/truerag/api` and `/truerag/worker` respectively and are queryable via CloudWatch Logs Insights

---

### Story 10.3: CloudWatch Alarms & RAGAS Regression Alerting

As a Platform Admin,
I want CloudWatch alarms provisioned for RAGAS regression detection and critical infrastructure metrics,
So that quality regressions and infrastructure failures trigger automatic notifications without manual monitoring (FR42, NFR13).

**Acceptance Criteria:**

**Given** `terraform/modules/cloudwatch/`
**When** applied
**Then** a CloudWatch alarm is configured on the custom RAGAS faithfulness metric (written by `eval_service.py`) that triggers when the metric falls below the configured threshold; the alarm is connected to an SNS topic with an email subscription

**Given** the RAGAS regression alarm triggers
**When** SNS delivers the notification
**Then** the notification includes `tenant_id`, `agent_id`, the score that triggered the alert, and the threshold value; v1 delivers email only — Slack/webhook deferred to v2 as documented in the ADR

**Given** infrastructure alarms provisioned in Terraform
**When** inspected
**Then** alarms exist for: ECS service `truerag-api` unhealthy task count > 0, RDS CPU utilisation > 80%, SQS DLQ message count > 0 (indicating failed ingestion jobs requiring investigation)

---

### Story 10.4: GitHub Actions CI-CD Pipeline with RAGAS Eval Gate

As an AI Platform Engineer,
I want a full CI-CD pipeline that runs tests and type checks on every PR, and blocks deployments when RAGAS scores fall below the configured threshold against a dedicated eval agent on the production deployment,
So that code quality and retrieval quality are both enforced automatically before any change reaches users (NFR22).

**Acceptance Criteria:**

**Given** a pull request is opened against `main`
**When** the `ci.yml` workflow runs
**Then** Ruff linting, mypy strict type checking, and the full pytest suite (unit + integration) must all pass; a failing check blocks merge

**Given** the `deploy.yml` workflow triggers on merge to `main`
**When** it executes
**Then** it builds a Docker image, pushes to the `truerag` ECR repository, deploys the new image to ECS via a rolling deployment (minimum healthy percent preserving old tasks during rollout), then runs `POST /v1/agents/{eval_agent_id}/eval/run` against a dedicated eval agent on the production deployment before the rollout completes

**Given** no separate staging environment exists in v1
**When** the RAGAS eval gate runs
**Then** it targets a dedicated eval agent (`eval_agent_id`) provisioned on the production deployment for this purpose — this agent has a stable golden dataset and indexed documents used solely for CI-CD quality gates; the chosen approach (dedicated prod eval agent vs. task-level routing) is documented in `docs/adrs/`

**Given** the RAGAS eval gate returns a `faithfulness` score below the configured threshold
**When** `deploy.yml` processes the result
**Then** the ECS rolling deployment is halted; the old tasks continue serving traffic; the workflow exits with a non-zero status and the failure is visible in the GitHub Actions run summary

**Given** the eval run exceeds 20 questions (async path from Story 6.2)
**When** the pipeline waits for results
**Then** `deploy.yml` polls `GET /v1/agents/{eval_agent_id}/eval/history` for the `run_id` with a configurable timeout (default: 10 minutes); if the timeout is exceeded the deployment is halted
