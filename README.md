# TrueRAG

Production-grade multi-tenant RAG engine. Pluggable vector stores, LLMs, embedders, chunkers, and rerankers — all switchable per agent via config, zero code changes.

---

## Architecture

### System Overview

```mermaid
graph TB
    Client["Client / CI Gate"]

    subgraph API["API Layer (FastAPI)"]
        Routes["Routes /v1/*"]
        Auth["Auth + RBAC Middleware"]
        RateLimit["Rate Limiter"]
    end

    subgraph Services["Service Layer"]
        AgentSvc["Agent Service"]
        QuerySvc["Query Service"]
        IngestSvc["Ingestion Service"]
        EvalSvc["Eval Service"]
        TenantSvc["Tenant Service"]
    end

    subgraph Pipelines["Pipeline Layer"]
        QueryPipe["Query Pipeline"]
        IngestPipe["Ingestion Pipeline"]
    end

    subgraph Providers["Provider Registry"]
        VS["Vector Store\npgvector · Qdrant · Pinecone"]
        Embed["Embedder\nOpenAI · Cohere · Bedrock"]
        LLM["LLM\nAnthropic · OpenAI · Bedrock"]
        Chunk["Chunker\nFixed · Semantic · Hierarchical · Doc-Aware"]
        Rerank["Reranker\nCross-Encoder · Cohere · None"]
    end

    subgraph Queue["Queue Backend"]
        Kafka["Kafka"]
        SQS["SQS"]
        Local["Local (dev)"]
    end

    subgraph Storage["Storage"]
        Mongo[("MongoDB\nTenants · Agents · Docs")]
        PG[("PostgreSQL\npgvector")]
        Cache["Semantic Cache\n(pgvector)"]
    end

    Client --> Auth
    Auth --> RateLimit --> Routes
    Routes --> Services
    AgentSvc & TenantSvc --> Mongo
    QuerySvc --> QueryPipe
    IngestSvc --> Queue
    Queue --> IngestPipe
    QueryPipe & IngestPipe --> Providers
    Providers --> VS & Embed & LLM & Chunk & Rerank
    VS --> PG
    QuerySvc --> Cache
```

---

### Query Pipeline

```mermaid
flowchart LR
    Q["User Query"] --> Scrub["PII Scrub"]
    Scrub --> Cache{"Semantic\nCache Hit?"}
    Cache -- hit --> Resp["Response"]
    Cache -- miss --> Budget{"Budget\nCheck"}
    Budget -- exceeded --> Err429["429 Rate Limited"]
    Budget -- ok --> Route{"Query\nRouter"}

    Route -- direct --> Gen["LLM Generate"]
    Route -- retrieval --> Rewrite{"Query\nRewrite?"}

    Rewrite -- yes --> Rewriter["LLM Rewriter"]
    Rewrite -- no --> Strategy

    Rewriter --> Strategy{"Retrieval\nStrategy"}

    Strategy -- dense --> Embed["Embed Query"]
    Strategy -- sparse --> BM25["BM25 Search"]
    Strategy -- hybrid --> Both["Dense + Sparse\n→ RRF Merge"]
    Strategy -- hyde --> HyDE["Generate Hypothesis\n→ Embed"]
    Strategy -- multi-query --> MQ["Generate N Variants\n→ RRF Merge"]

    Embed & BM25 & Both & HyDE & MQ --> Rerank["Reranker\n(pool → top_k)"]
    Rerank --> MMR{"MMR\nFilter?"}
    MMR --> Gen

    Gen --> Faith{"Faithfulness\nCheck?"}
    Faith --> CacheStore["Cache Store"]
    CacheStore --> Audit["Audit Log\n+ Cost Track"]
    Audit --> Resp
```

---

### Ingestion Pipeline

```mermaid
flowchart LR
    Upload["Document Upload\n(API)"] --> Record["Create DB Record\n(pending)"]
    Record --> Queue["Enqueue Job\nKafka / SQS / Local"]
    Queue --> Worker["Ingestion Worker"]

    Worker --> Fetch["Fetch from S3\n/ Local Store"]
    Fetch --> Parse["Parse\nPDF · DOCX · TXT · MD\n+ OCR fallback\n+ table extract"]
    Parse --> PII["PII Scrub\n(Presidio)"]
    PII --> Chunk["Chunk\nFixed · Semantic\nHierarchical · Doc-Aware"]
    Chunk --> Dedup["Hash Dedup\n(skip unchanged chunks)"]
    Dedup --> Embed["Embed Chunks\n(batch)"]
    Embed --> Upsert["Upsert Vector Store"]
    Upsert --> MarkReady["Mark Document Ready\n+ Archive Predecessor"]

    Worker -- failure --> DLQ["DLQ / Retry\n(3 attempts)"]
    DLQ -- permanent --> MarkFailed["Mark Document Failed"]
```

---

### Multi-Tenant Isolation

```mermaid
graph LR
    subgraph TenantA["Tenant A"]
        A1["Agent A1\nnamespace: tenantA_agentA1"]
        A2["Agent A2\nnamespace: tenantA_agentA2"]
    end
    subgraph TenantB["Tenant B"]
        B1["Agent B1\nnamespace: tenantB_agentB1"]
    end

    A1 & A2 & B1 --> VS["Vector Store\n(namespace-scoped reads/writes)"]
    A1 & A2 & B1 --> Mongo["MongoDB\n(tenant_id filter on all queries)"]

    VS -- "NamespaceViolationError\non mismatch" --> Guard["Isolation Guard"]
```

---

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Set API keys for the providers you want to use
```

### 2. Run (Docker)

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Docs | http://localhost:8000/docs |
| Health | http://localhost:8000/v1/health |

### 3. Run bare-metal (optional)

```bash
# Start only infra
docker compose up mongodb postgres kafka

# Install deps
uv sync
source .venv/bin/activate
python -m spacy download en_core_web_sm

# API
uvicorn app.main:app --reload

# Worker (separate terminal)
python -m app.workers.entrypoint
```

### 4. Seed a tenant

```bash
python scripts/seed_tenant.py
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `local` | `local` reads keys from env; else uses AWS Secrets Manager |
| `LOG_LEVEL` | `INFO` | `DEBUG` · `INFO` · `WARNING` · `ERROR` |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection |
| `PGVECTOR_DSN` | `postgresql://postgres:postgres@localhost:5432/truerag` | PostgreSQL DSN |
| `QUEUE_BACKEND` | `kafka` | `kafka` · `sqs` · `local` |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka brokers |
| `DEFAULT_RATE_LIMIT_RPM` | `60` | Per-tenant rate limit |
| `OPENAI_API_KEY` | — | OpenAI LLM / embeddings |
| `ANTHROPIC_API_KEY` | — | Anthropic LLM |
| `COHERE_API_KEY` | — | Cohere embeddings / reranker |
| `QDRANT_API_KEY` | — | Qdrant vector store |
| `PINECONE_API_KEY` | — | Pinecone vector store |

---

## API Reference

Authentication: `X-API-Key: <key>` on all requests.

```
# Tenants
POST   /v1/tenants                           Create tenant (admin)
GET    /v1/tenants                           List tenants (admin)
GET    /v1/tenants/me                        Current tenant

# Agents
POST   /v1/agents                            Create agent
GET    /v1/agents                            List agents (cursor-paginated)
GET    /v1/agents/{id}                       Get agent
PATCH  /v1/agents/{id}/config                Update agent config

# Documents
POST   /v1/agents/{id}/documents             Upload & ingest document
GET    /v1/agents/{id}/documents             List documents
GET    /v1/agents/{id}/documents/{doc_id}    Document status
DELETE /v1/agents/{id}/documents/{doc_id}    Delete document

# Query
POST   /v1/agents/{id}/query                 Query (JSON or SSE stream)
GET    /v1/agents/{id}/sessions              List conversation sessions
GET    /v1/agents/{id}/sessions/{sid}        Session message history

# Eval
POST   /v1/agents/{id}/eval                  Create / replace eval dataset
GET    /v1/agents/{id}/eval                  Get eval dataset
POST   /v1/agents/{id}/eval/run              Run RAGAS evaluation
GET    /v1/agents/{id}/eval/history          Eval run history

# Observability
GET    /v1/metrics                           Prometheus metrics
GET    /v1/metrics/costs                     Token cost breakdown
GET    /v1/configs                           Available provider options
GET    /v1/health                            Health
GET    /v1/ready                             Readiness
```

---

## Provider Matrix

| Category | Providers |
|----------|-----------|
| Vector Store | `pgvector` (default) · `qdrant` · `pinecone` |
| Embedder | `openai` · `cohere` · `bedrock` |
| LLM | `anthropic` · `openai` · `bedrock` |
| Chunker | `fixed_size` · `semantic` · `hierarchical` · `document_aware` · `keyword` |
| Reranker | `none` · `cross_encoder` · `cohere` |
| Retrieval | `dense` · `sparse` (BM25) · `hybrid` (RRF) |

Adding a new provider = implement the ABC in `app/providers/{category}/` + one line in `app/providers/registry.py`. Nothing else changes.

---

## Tests

```bash
uv sync
source .venv/bin/activate

pytest                   # unit tests
pytest -m integration    # requires running databases
```

---

## Project Structure

```
app/
  api/v1/        Routes (FastAPI)
  core/          Config, auth, RBAC, middleware, errors
  db/dao/        MongoDB DAO (Beanie ODM)
  interfaces/    Abstract provider ABCs
  models/        Beanie documents + Pydantic schemas
  pipelines/     Ingestion + query orchestration
  providers/     Concrete implementations + registry
  services/      Business logic
  utils/         Observability, PII, cost tracker, secrets
  workers/       Ingestion worker (Kafka / SQS / local)
scripts/
  seed_tenant.py
infra/
  terraform/     AWS ECS, ALB, DynamoDB, SQS, CloudWatch
  .github/       CI (lint + test) + CD (build → ECR → ECS → eval gate)
tests/
```
