# TrueRAG

Production-grade open-source RAG Engine. Part of TruePlatform.

## Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for bare-metal / tests)
- [`uv`](https://github.com/astral-sh/uv)

## Running Locally

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and add API keys for the LLM providers you plan to use:

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
