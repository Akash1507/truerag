# TrueRAG

Production-grade open-source RAG engine. Part of TruePlatform.

Multi-tenant, multi-provider retrieval-augmented generation platform with pluggable vector stores, LLMs, embeddings, chunking strategies, and rerankers — all switchable per agent via config with no code changes.

## Features

- **Multi-tenant** — isolated namespaces per tenant/agent, RBAC (admin / agent_owner / reader)
- **Pluggable providers** — vector stores (pgvector, Qdrant, Pinecone), LLMs (Anthropic, OpenAI, Bedrock), embeddings (OpenAI, Cohere, Bedrock), rerankers (cross-encoder, Cohere, none)
- **Retrieval modes** — dense, sparse (BM25), hybrid (dense + BM25 + RRF)
- **Advanced chunking** — fixed, semantic (spaCy + sentence-transformers), hierarchical (parent/child), document-aware (Markdown/table-aware)
- **Conversation memory** — multi-turn sessions with sliding-window context compaction (8192-token limit)
- **Streaming** — SSE token-by-token query responses
- **Semantic cache** — cosine-similarity deduplication of repeated queries
- **Eval pipeline** — RAGAS (faithfulness, answer relevancy, context recall/precision) with regression detection
- **Observability** — Prometheus metrics, structured JSON logging, per-stage latency tracking

## Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for bare-metal / tests)
- [`uv`](https://github.com/astral-sh/uv)

## Running Locally

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and add API keys for the providers you plan to use:

```dotenv
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
COHERE_API_KEY=...
```

### 2. Start all services

```bash
docker compose up --build
```

This starts MongoDB, PostgreSQL+pgvector, Kafka, the API server, and the ingestion worker.

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/v1/health |
| MongoDB | localhost:27017 |
| PostgreSQL | localhost:5432 |
| Kafka | localhost:9092 |

### 3. Start only infrastructure (optional)

If you want to run the API process directly on your machine:

```bash
# Start databases + kafka only
docker compose up mongodb postgres kafka

# Install dependencies
uv sync --no-dev
source .venv/bin/activate
python -m spacy download en_core_web_sm

# Point to localhost services
sed -i 's/mongodb:27017/localhost:27017/; s/@postgres:5432/@localhost:5432/; s/kafka:9092/localhost:9092/' .env

# Run API
uvicorn app.main:app --reload

# Run worker (separate terminal)
python -m app.workers.entrypoint
```

## Running Tests

```bash
uv sync
source .venv/bin/activate

# Unit tests
pytest

# Integration tests (require running databases)
pytest -m integration
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `local` | `local` reads API keys from env directly; other values use AWS Secrets Manager |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `OPENAI_API_KEY` | — | Required if using OpenAI LLM or embeddings |
| `ANTHROPIC_API_KEY` | — | Required if using Anthropic LLM |
| `COHERE_API_KEY` | — | Required if using Cohere embeddings or reranker |
| `QDRANT_API_KEY` | — | Required if using Qdrant vector store |
| `PINECONE_API_KEY` | — | Required if using Pinecone vector store |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection URI |
| `PGVECTOR_DSN` | `postgresql://postgres:postgres@localhost:5432/truerag` | PostgreSQL DSN |
| `QUEUE_BACKEND` | `kafka` | `kafka`, `sqs`, or `local` |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka brokers |
| `DEFAULT_RATE_LIMIT_RPM` | `60` | Per-tenant rate limit (requests/min) |

## API Overview

```
POST   /v1/tenants                          Create tenant
GET    /v1/tenants/me                       Current tenant info

POST   /v1/agents                           Create agent
GET    /v1/agents                           List agents (cursor-paginated)
GET    /v1/agents/{id}                      Get agent
PATCH  /v1/agents/{id}/config               Update agent config

POST   /v1/agents/{id}/documents            Upload document (triggers ingestion)
GET    /v1/agents/{id}/documents            List documents
DELETE /v1/agents/{id}/documents/{doc_id}   Delete document

POST   /v1/agents/{id}/query                Query (streaming SSE or JSON)
GET    /v1/agents/{id}/sessions             List conversation sessions
GET    /v1/agents/{id}/sessions/{sid}       Get session messages

POST   /v1/agents/{id}/eval                 Create eval dataset
GET    /v1/agents/{id}/eval                 Get eval dataset
POST   /v1/agents/{id}/eval/run             Run RAGAS evaluation
GET    /v1/agents/{id}/eval/history         Eval run history

GET    /v1/metrics                          Prometheus metrics
GET    /v1/metrics/costs                    Token cost breakdown
GET    /v1/configs                          Available provider options
GET    /v1/health                           Health check
GET    /v1/ready                            Readiness check
```

Authentication: `X-API-Key: <key>` header on all requests.

## Architecture Decisions

Key decisions made during development, captured here for contributors.

### Provider Abstraction (ADR-008)

Five abstract base classes in `app/interfaces/` define locked contracts:

| Interface | Method | Sync/Async |
|-----------|--------|------------|
| `VectorStore` | `upsert`, `query`, `delete_namespace`, `health` | async |
| `ChunkingStrategy` | `chunk` | sync |
| `Reranker` | `rerank` | sync |
| `EmbeddingProvider` | `embed` | async |
| `LLMProvider` | `generate` | async |

Adding a new provider requires exactly **two changes**: implement the ABC in `app/providers/{category}/`, then register it in `app/providers/registry.py`. No service, pipeline, or router file is touched.

`PassthroughReranker` satisfies the `Reranker` interface with a no-op, making reranking opt-in without pipeline conditionals.

`app/core/dependencies.py` is the **only** file permitted to read from registries — all other code receives provider instances via FastAPI dependency injection.

### Chunking Strategies (ADR-007)

- **Semantic**: spaCy sentence segmentation + `sentence-transformers` embeddings; greedily merge adjacent sentences while cosine similarity ≥ 0.75; `tiktoken` enforces max token size.
- **Hierarchical**: large parent windows (1024 tokens) split into child windows (256 tokens, 25 overlap); parent text embedded in `ChunkMetadata.parent_text`.
- **Document-aware**: line-based regex detection of Markdown headings, dividers, and tables; splits by structural sections; fixed-window subchunking for oversized sections.

### Vector Stores

- **pgvector** — default, no extra infra; one table per namespace.
- **Qdrant** (ADR-011) — `AsyncQdrantClient`, one collection per `{tenant_id}_{agent_id}` namespace; namespace verified on every query result.
- **Pinecone** (ADR-012) — shared index `truerag`, Pinecone native namespaces for isolation; SDK calls wrapped in `asyncio.to_thread`.

All three enforce namespace isolation at the read path and raise `NamespaceViolationError` on mismatch.

Embedding provider change with existing vectors sets `embedding_provider_mismatch=True` on the agent, blocking queries until a full reindex is enqueued (ADR-013).

### Retrieval Modes (ADR-008)

- **dense** — ANN vector similarity.
- **sparse** — query-time BM25 (`rank-bm25`, `BM25Okapi`) built from corpus fetched from the agent namespace. O(N) per query; acceptable at MVP scale. Persistent sparse index deferred to when p95 latency regresses at scale.
- **hybrid** — dense + sparse in parallel, fused via Reciprocal Rank Fusion (RRF).

### Reranking (ADR-009)

Retrieve-wide-rerank-narrow pattern: fetch `max(top_k, rerank_pool_size)` candidates, rerank, truncate to `top_k`.

- `cross_encoder` — `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers`, synchronous, local inference.
- `cohere` — `rerank-english-v3.0` via Cohere API, key from AWS Secrets Manager.
- `none` — `PassthroughReranker`, no-op.

### Rate Limiting (ADR-007)

In-process fixed-window counter per tenant per minute via `RateLimiterMiddleware`. Each replica maintains its own `_counters` dict — effective limit is `N × rpm` across N replicas. No Redis dependency for v1. Redis-backed sliding window deferred to v2.

### LLM Providers (ADR-014)

`OpenAILLMProvider` (chat completions) and `BedrockLLMProvider` (`bedrock-runtime:InvokeModel`, Anthropic schema by default), both registered in `LLM_REGISTRY`. Failures normalized to `ProviderUnavailableError`.

### Metrics (ADR-011)

In-process Prometheus counters/histograms (`prometheus_client`), reset on restart by design. Counter resets handled in dashboards with `increase()`. Worker ingestion counts sourced from CloudWatch log metric filters on structured logs, not API-process memory.

### Eval & Regression Detection (ADR-018, ADR-019)

RAGAS evaluation (`faithfulness`, `answer_relevancy`, `context_recall`, `context_precision`) runs via `POST /v1/agents/{id}/eval/run`. When faithfulness drops below the agent's configured threshold, a `FaithfulnessRegression` CloudWatch metric is emitted (namespace `TrueRAG/EvalQuality`, dimensions `tenant_id`/`agent_id`). CloudWatch Alarm → SNS → email for alert delivery in v1; Slack/webhooks deferred to v2.

For CI/CD: run `ci.yml` on PRs (Ruff, mypy strict, pytest). Run `deploy.yml` on `main` (Docker build → ECR → ECS rolling deploy → blocking RAGAS eval gate against a dedicated eval agent). If the eval gate fails, the deployment is marked failed; manual rollback via task definition revision.

## Project Structure

```
app/
  api/v1/          HTTP routes (FastAPI)
  core/            Config, auth, middleware, errors, decorators
  db/dao/          MongoDB DAO layer (Beanie ODM)
  interfaces/      Abstract provider ABCs (locked contracts)
  models/          Beanie documents + Pydantic schemas
  pipelines/       Ingestion and query pipeline orchestration
  providers/       Concrete provider implementations + registry
  services/        Business logic (agent, query, eval, tenant, audit, metrics)
  utils/           Observability, cost tracker, file store, secrets
  workers/         Ingestion worker (Kafka/SQS/local queue)
scripts/
  seed_tenant.py   Bootstrap a tenant + agent for local dev
tests/
  pipelines/
  workers/
  conftest.py
```
