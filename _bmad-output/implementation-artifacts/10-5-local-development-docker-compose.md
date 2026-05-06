# Story 10-5: Local Development Docker Compose

**Epic:** 10 — Production Deployment & Operations (addendum)
**Status:** review
**Depends on:** 3-5 (pluggable queue backend — `QUEUE_BACKEND=local` or LocalStack SQS)
**Sprint Change Proposal:** sprint-change-proposal-2026-05-07.md

## User Story

As a Developer,
I want a `docker-compose.yml` that starts the full TrueRAG stack locally with one command,
So that I can develop and test without AWS credentials, LocalStack, or manual service setup.

## Background

Currently no `docker-compose.yml` exists. Only a `Dockerfile` is present. Developers must:
1. Have MongoDB running locally
2. Have PostgreSQL + pgvector running locally
3. Have LocalStack or real AWS for SQS/S3
4. Manually create SQS queues and S3 buckets
5. Set ~15 env vars correctly

This is a high barrier. Story 10-5 brings it to: `docker-compose up`.

## Acceptance Criteria

**Given** `docker-compose up` is run in the repo root
**When** all services start
**Then** MongoDB on 27017, PostgreSQL+pgvector on 5432, and the API on 8000 are all healthy within 60 seconds

**Given** `QUEUE_BACKEND=local` is set in `.env.local`
**When** a document is uploaded via the API
**Then** the worker processes it using `LocalQueueBackend` — no LocalStack required

**Given** `QUEUE_BACKEND=sqs` is set in `.env.local`
**When** a document is uploaded via the API
**Then** the worker processes it using LocalStack SQS (LocalStack service must be running)

**Given** `docker-compose up` is run
**When** the `init` service completes
**Then** SQS queue `truerag-ingestion` and S3 bucket `truerag-documents` are created in LocalStack (if LocalStack profile used)

**Given** a developer modifies source files
**When** the api/worker containers are running with `./app:/app/app` volume mount
**Then** uvicorn auto-reloads reflect changes without container restart

**Given** `.env.local` does not exist
**When** developer runs `cp .env.local.example .env.local`
**Then** all required variables have working local defaults; no manual editing required for basic local dev

**Given** `docker-compose down -v` is run
**When** complete
**Then** all volumes purged; next `docker-compose up` starts fresh

## Implementation Notes

### New file: `docker-compose.yml`

```yaml
version: "3.9"

services:
  mongodb:
    image: mongo:7
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 10s
      timeout: 5s
      retries: 5

  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: truerag
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  localstack:
    image: localstack/localstack:3
    ports:
      - "4566:4566"
    environment:
      SERVICES: sqs,s3
      DEFAULT_REGION: us-east-1
      PERSISTENCE: 1
    volumes:
      - localstack_data:/var/lib/localstack
    profiles:
      - localstack  # only started with: docker-compose --profile localstack up

  init:
    image: amazon/aws-cli:2.15.0
    depends_on:
      localstack:
        condition: service_healthy
    environment:
      AWS_ACCESS_KEY_ID: test
      AWS_SECRET_ACCESS_KEY: test
      AWS_DEFAULT_REGION: us-east-1
    entrypoint: >
      /bin/sh -c "
        aws --endpoint-url=http://localstack:4566 sqs create-queue --queue-name truerag-ingestion &&
        aws --endpoint-url=http://localstack:4566 s3 mb s3://truerag-documents
      "
    profiles:
      - localstack

  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env.local
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    volumes:
      - ./app:/app/app
    depends_on:
      mongodb:
        condition: service_healthy
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/v1/health"]
      interval: 15s
      timeout: 5s
      retries: 5

  worker:
    build: .
    env_file: .env.local
    command: python -m app.workers.entrypoint
    volumes:
      - ./app:/app/app
    depends_on:
      mongodb:
        condition: service_healthy

volumes:
  mongo_data:
  pg_data:
  localstack_data:
```

### New file: `.env.local.example`

```env
# TrueRAG — local development environment
# Copy to .env.local and adjust as needed.
# No AWS credentials required when QUEUE_BACKEND=local.

APP_ENV=local
LOG_LEVEL=DEBUG

# Queue backend: "local" (no AWS needed) | "sqs" (requires LocalStack profile) | "kafka"
QUEUE_BACKEND=local

# MongoDB
MONGODB_URI=mongodb://mongodb:27017
MONGODB_DATABASE=truerag

# PostgreSQL + pgvector
PGVECTOR_DSN=postgresql://postgres:postgres@postgres:5432/truerag

# AWS / LocalStack (only needed when QUEUE_BACKEND=sqs)
AWS_REGION=us-east-1
AWS_ENDPOINT_URL=http://localstack:4566
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
SQS_INGESTION_QUEUE_URL=http://localstack:4566/000000000000/truerag-ingestion
S3_DOCUMENT_BUCKET=truerag-documents

# Kafka (only needed when QUEUE_BACKEND=kafka)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_TOPIC=truerag-ingestion

# Rate limiting
DEFAULT_RATE_LIMIT_RPM=1000

# Semantic cache
SEMANTIC_CACHE_TTL_HOURS=24

# LLM / Embedding providers (real keys needed for E2E testing)
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=...
# COHERE_API_KEY=...
```

### New file: `app/workers/entrypoint.py`

```python
"""Worker entrypoint — starts SQS consumer loop."""
import asyncio

from app.core.config import get_settings
from app.providers.queue import get_queue_backend
from app.utils.observability import configure_logging
from app.workers.sqs_consumer import run_consumer


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    backend = get_queue_backend(settings)
    await run_consumer(backend, settings)


if __name__ == "__main__":
    asyncio.run(main())
```

### Dockerfile update (hot-reload support)

Add `uvicorn` with `--reload` support — the `docker-compose.yml` overrides CMD at compose level for dev. The production `Dockerfile` CMD stays as gunicorn. No change required to `Dockerfile`.

### pgvector extension init

Add `docker-compose.override.yml` for pgvector extension creation:

```yaml
# docker-compose.override.yml — auto-loaded by docker-compose
version: "3.9"
services:
  postgres:
    environment:
      POSTGRES_INITDB_ARGS: "--encoding=UTF8"
    volumes:
      - ./scripts/init-pgvector.sql:/docker-entrypoint-initdb.d/init-pgvector.sql
```

```sql
-- scripts/init-pgvector.sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Quick Start (developer guide)

```bash
# 1. Clone + setup
cp .env.local.example .env.local

# 2. Start (no AWS needed — uses local queue)
docker-compose up

# 3. API available at
curl http://localhost:8000/v1/health

# 4. With LocalStack SQS (optional)
docker-compose --profile localstack up

# 5. Teardown
docker-compose down -v
```

## Test Requirements

- Smoke test: `docker-compose up` → all health checks pass within 60s (manual / CI)
- Verify `QUEUE_BACKEND=local` → document upload → worker processes → status=ready (no AWS)
- Verify `QUEUE_BACKEND=sqs` with LocalStack → same flow

## Definition of Done

- [x] `docker-compose.yml` at repo root
- [x] `.env.local.example` at repo root (`.env.local` in `.gitignore`)
- [x] `docker-compose.override.yml` with pgvector init SQL
- [x] `scripts/init-pgvector.sql` created
- [x] `app/workers/entrypoint.py` created
- [ ] `docker-compose up` starts api + worker + mongodb + postgres with healthchecks
- [ ] `QUEUE_BACKEND=local` works end-to-end without any AWS service
- [x] `.env.local` added to `.gitignore`

## Tasks / Subtasks

- [x] Add `docker-compose.yml` with services: `mongodb`, `postgres` (pgvector), `api`, `worker`, and optional `localstack` + `init`
- [x] Add healthchecks and source mounts for local development hot-reload
- [x] Add `.env.local.example` with working local defaults for `QUEUE_BACKEND=local`
- [x] Add `docker-compose.override.yml` and `scripts/init-pgvector.sql` for pgvector extension init
- [x] Add `app/workers/entrypoint.py` that configures logging and starts consumer via backend factory (with compatibility fallback)
- [x] Ensure `.env.local` is ignored in git

## Dev Agent Record

### Debug Log

- 2026-05-07: Implemented local Docker Compose stack and local environment defaults.
- 2026-05-07: Added worker entrypoint with queue-backend-first startup path and fallback to existing SQS-session consumer signature.
- 2026-05-07: Added pgvector init SQL and compose override mount.

### Completion Notes

- Compose stack now supports default local queue mode and optional LocalStack profile.
- Worker entrypoint is forward-compatible with story 3-5 backend factory refactor while preserving current runtime behavior.
- No changes were made outside the ownership list.

## File List

- `docker-compose.yml` (new)
- `docker-compose.override.yml` (new)
- `.env.local.example` (new)
- `scripts/init-pgvector.sql` (new)
- `app/workers/entrypoint.py` (new)
- `.gitignore` (updated)

## Change Log

| Date       | Change |
|------------|--------|
| 2026-05-07 | Added local development Docker Compose stack with optional LocalStack profile and init helper |
| 2026-05-07 | Added local env template defaults and ignored `.env.local` |
| 2026-05-07 | Added pgvector init SQL and worker container entrypoint |

## Status

review
