# Sprint Change Proposal: Architecture Consistency, Loguru Logging, Class-Based Services & Local Dev

**Date:** 2026-05-07
**Requested by:** Akash
**Scope:** MODERATE — Developer agent implementation + PO backlog reorganization
**Status:** PENDING APPROVAL

---

## Section 1: Issue Summary

**Problem statement:** Six cross-cutting inconsistencies were identified during sprint execution that collectively degrade code quality, observability, testability, and developer experience. None of these were revealed by a single story — they accumulated across Epics 1–10 and are now visible as the codebase grows.

**Evidence:**

| # | Issue | Concrete Example |
|---|-------|-----------------|
| 1 | Router inconsistency: mixed try-except + manual model mapping | `agents.py` does `AgentCreateResponse(**agent.model_dump())` but `documents.py` returns service result directly; `list_agents_route` has `try/except ValueError` but `query.py` has none |
| 2 | No generic service error decorator | Each service function handles errors ad-hoc; `ValueError` from cursor decode leaks to router layer forcing duplicate try-except blocks |
| 3 | No log standardization or masking | Custom stdlib `JSONFormatter` in `observability.py`; no sensitive field masking; no structured loguru integration |
| 4 | Free functions in every service file | `upload_document`, `get_document_status`, `list_agents`, etc. are all module-level free functions — no cohesion, no DI, hard to test |
| 5 | Request/response logging missing | No middleware captures request body / response body with sensitive field masking |
| 6 | AWS lock-in, no local dev | `sqs_consumer.py` directly uses `aioboto3` SQS; `ingestion_service.py` directly calls S3; no `docker-compose.yml` |

**Discovery context:** Cross-cutting code review during Epic 9 (Observability) and Epic 10 (Deployment) work. The logging inconsistencies became acute when wiring Prometheus metrics (Epic 9); the AWS lock-in became acute during local testing of CI-CD pipeline (Epic 10).

---

## Section 2: Impact Analysis

### Epic Impact

| Epic | Status | Impact |
|------|--------|--------|
| Epic 1 — Platform Foundation & Security Baseline | **done** | Needs 3 new addendum stories (1-11, 1-12, 1-13): loguru, error decorator, class-based services |
| Epic 3 — Async Document Ingestion Pipeline | **in-progress** | Needs new story 3-5: pluggable queue backend abstraction (SQS → interface) |
| Epic 9 — Platform Observability | **in-progress** | Logging standardization (1-11) is a direct dependency; 9-x stories must build on loguru |
| Epic 10 — Production Deployment | **in-progress** | Needs new story 10-5: Docker Compose + local dev environment |

Epics 2, 4, 5, 6, 7, 8 (all done) — code will be refactored as part of 1-13 class-based services story but their acceptance criteria remain satisfied.

### Story Impact

**Stories requiring code changes (not re-scoping):**
- All router files (`query.py`, `documents.py`, `agents.py`, `tenants.py`, `eval.py`, `observability.py`) — remove try-except, remove manual model mapping
- All service files — refactored to classes as part of story 1-13
- `app/utils/observability.py` — replaced with loguru in story 1-11
- `app/workers/sqs_consumer.py` — refactored to use queue interface in story 3-5

**New stories:**
- `1-11-loguru-logging-request-response-middleware-with-masking.md`
- `1-12-generic-service-error-decorator.md`
- `1-13-class-based-service-architecture-solid-refactor.md`
- `3-5-pluggable-queue-backend-sqs-kafka-local.md`
- `10-5-local-development-docker-compose.md`

### Artifact Conflicts

**Architecture doc** (`_bmad-output/planning-artifacts/architecture.md`):
- Add: Service layer class diagram (repository pattern with DI)
- Add: Queue abstraction layer (QueueBackend interface + implementations)
- Update: Logging section — stdlib → loguru, add masking policy
- Add: Local development section

**pyproject.toml:**
- Add: `loguru>=0.7.0,<1.0.0`
- Add: `kafka-python-ng>=2.2.0,<3.0.0` (optional, for Kafka backend)

### Technical Impact

- **No API contract changes** — all endpoints remain identical
- **No data model changes** — MongoDB/PostgreSQL schemas unaffected
- **Test updates required** — service tests mock free functions today; must be updated to mock injected class instances
- **Import path changes** — `from app.services import agent_service` → `from app.services.agent_service import AgentService`; routers updated to inject via FastAPI `Depends`

---

## Section 3: Recommended Approach

**Selected: Option 1 — Direct Adjustment** (add new stories, refactor in-place)

**Rationale:**
- No rollback needed — the issues are additive (missing abstractions) not blocking (code works)
- New stories can be sequenced without disturbing in-progress Epic 9/10 stories
- Class-based refactor (1-13) subsumes the router consistency fix, making it one coordinated change
- Loguru swap (1-11) is self-contained and can be done first — unblocks better logging in 9-x stories
- Docker Compose (10-5) is purely additive — zero risk to existing infra

**Sequencing:**
```
1-11 (loguru)  →  1-12 (decorator)  →  1-13 (class-based + router consistency)
3-5 (queue abstraction)   [parallel to 1-x]
10-5 (docker compose)     [parallel to all]
```

**Effort:** Medium (5 stories, ~2–3 sprints)
**Risk:** Medium — 1-13 touches every service and router file; mitigated by existing test suite

---

## Section 4: Detailed Change Proposals

---

### CP-1: Router Consistency — Return Service Result Directly, No Try-Except

**Scope:** All router files in `app/api/v1/`

**Problem:** Routers mix three patterns:
1. `return ServiceResponse(**service_result.model_dump())` — manual re-mapping
2. `try: ... except ValueError: raise InvalidCursorError(...)` — error translation in router
3. `return await service.method(...)` — clean direct return

**Fix:** Pattern 3 only. Services return correctly-typed response objects. `ValueError` from cursor decode converted by service error decorator (CP-2) before reaching router.

**OLD (agents.py `create_agent_route`):**
```python
agent = await agent_service.create_agent(body, caller.tenant_id)
return AgentCreateResponse(**agent.model_dump())
```

**NEW:**
```python
return await agent_service.create(body, caller.tenant_id)
```

**OLD (agents.py `list_agents_route`):**
```python
try:
    items, next_cursor = await agent_service.list_agents(caller.tenant_id, cursor, limit)
except ValueError as exc:
    raise InvalidCursorError(str(exc)) from exc
return AgentListResponse(
    items=[AgentCreateResponse(**item.model_dump()) for item in items],
    next_cursor=next_cursor,
)
```

**NEW:**
```python
return await agent_service.list(caller.tenant_id, cursor, limit)
```

**Rationale:** Routers own HTTP binding only. Error translation and response shaping belong in the service layer.

---

### CP-2: Generic Service Error Decorator

**New file:** `app/core/decorators.py`

**Problem:** No consistent error capture, logging, or error translation in the service layer. `ValueError` from `decode_cursor` forces routers to contain business logic.

**NEW (decorator contract):**
```python
# app/core/decorators.py

import functools
from loguru import logger
from app.core.errors import InvalidCursorError, TrueRAGError

def service_method(operation: str):
    """Wraps async service methods: logs entry/exit, translates ValueError→InvalidCursorError."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            logger.bind(operation=operation).debug("service_call_start")
            try:
                result = await fn(*args, **kwargs)
                logger.bind(operation=operation).debug("service_call_ok")
                return result
            except TrueRAGError:
                raise  # already typed — let global handler deal with it
            except ValueError as exc:
                logger.bind(operation=operation).warning(f"invalid_cursor: {exc}")
                raise InvalidCursorError(str(exc)) from exc
            except Exception as exc:
                logger.bind(operation=operation).exception(f"unhandled_service_error: {exc}")
                raise
        return wrapper
    return decorator
```

**Rationale:** Single place for cross-cutting concerns. Routers no longer import error classes for translation.

---

### CP-3: Class-Based Service Architecture

**Scope:** All service modules

**Problem:** Free functions in every service file — no cohesion, tight coupling to global state (DAOs imported at module level), difficult to mock in tests.

**OLD (agent_service.py):**
```python
# Module-level free functions + module-level DAO imports
from app.db.dao.agent_dao import agent_dao
logger = get_logger(__name__)

async def create_agent(body: AgentCreateRequest, tenant_id: str) -> AgentDocument: ...
async def list_agents(tenant_id: str, cursor, limit) -> tuple[...]: ...
```

**NEW (agent_service.py):**
```python
from loguru import logger
from app.core.decorators import service_method
from app.db.dao.agent_dao import AgentDAO

class AgentService:
    def __init__(self, dao: AgentDAO) -> None:
        self._dao = dao

    @service_method("create_agent")
    async def create(self, body: AgentCreateRequest, tenant_id: str) -> AgentCreateResponse: ...

    @service_method("list_agents")
    async def list(self, tenant_id: str, cursor: str | None, limit: int) -> AgentListResponse: ...

    @service_method("get_agent")
    async def get(self, agent_id: str, tenant_id: str) -> AgentCreateResponse: ...

    @service_method("update_agent_config")
    async def update_config(self, agent_id: str, tenant_id: str, body: AgentConfigUpdateRequest) -> AgentUpdateResponse: ...

    @service_method("delete_agent")
    async def delete(self, agent_id: str, tenant_id: str, aws_session, settings) -> None: ...

# Singleton for DI
agent_service = AgentService(dao=agent_dao)
```

**Router injection (agents.py):**
```python
from app.services.agent_service import agent_service  # singleton

@router.post("", status_code=201, response_model=AgentCreateResponse)
async def create_agent_route(body: AgentCreateRequest, caller: TenantDocument = Depends(get_current_tenant)) -> AgentCreateResponse:
    return await agent_service.create(body, caller.tenant_id)
```

**SOLID compliance:**
- **S** — Each service class owns one domain (Agent, Tenant, Ingestion, Query, Eval, Metrics)
- **O** — New operations added as new methods; existing methods closed for modification
- **L** — Service classes honour consistent async interface contracts
- **I** — No fat interfaces; services only expose methods their callers need
- **D** — Routers depend on service abstraction, not DAO directly

---

### CP-4: Loguru Logging + Request/Response Middleware with Masking

**New/modified files:**
- `app/utils/observability.py` — replace stdlib with loguru
- `app/core/middleware.py` — add `RequestResponseLoggingMiddleware`

**OLD (observability.py):**
```python
import logging, json, sys
class JSONFormatter(logging.Formatter): ...
def get_logger(name: str) -> logging.Logger: ...
```

**NEW (observability.py):**
```python
import sys
from loguru import logger

SENSITIVE_FIELDS = frozenset({"api_key", "password", "authorization", "x-api-key", "token", "secret"})

def _mask(data: dict) -> dict:
    return {k: "***" if k.lower() in SENSITIVE_FIELDS else v for k, v in data.items()}

def configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        format="{time:ISO8601} | {level} | {extra[request_id]} | {extra[tenant_id]} | {extra[operation]} | {message}",
        serialize=True,  # JSON output
    )

def get_logger(name: str):  # backward-compat shim — returns bound logger
    return logger.bind(module=name, request_id="", tenant_id="", operation="")
```

**NEW (RequestResponseLoggingMiddleware):**
```python
class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):
    MASKED_HEADERS = frozenset({"authorization", "x-api-key"})

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        masked_headers = {
            k: "***" if k.lower() in self.MASKED_HEADERS else v
            for k, v in request.headers.items()
        }
        logger.bind(operation="http_request").info(
            f"{request.method} {request.url.path}",
            headers=masked_headers,
        )
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.bind(operation="http_response").info(
            f"{request.method} {request.url.path} → {response.status_code}",
            latency_ms=elapsed_ms,
        )
        return response
```

**Masking policy:**
- Request headers: `Authorization`, `X-Api-Key` → `***`
- Request/response body fields: `api_key`, `password`, `token`, `secret` → `***`
- Tenant IDs and agent IDs logged as-is (non-PII system identifiers)

---

### CP-5: Pluggable Queue Backend (SQS / Kafka / Local)

**New files:**
- `app/interfaces/queue_backend.py` — abstract base
- `app/providers/queue/sqs_backend.py`
- `app/providers/queue/local_backend.py` (asyncio Queue — for local dev + tests)
- `app/providers/queue/kafka_backend.py` (optional)

**NEW (queue_backend.py):**
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class QueueMessage:
    message_id: str
    body: dict
    receipt_handle: str
    receive_count: int

class QueueBackend(ABC):
    @abstractmethod
    async def send(self, payload: dict) -> None: ...

    @abstractmethod
    async def receive(self, max_messages: int = 1, wait_seconds: int = 20) -> list[QueueMessage]: ...

    @abstractmethod
    async def delete(self, receipt_handle: str) -> None: ...
```

**Config-driven selection (config.py):**
```python
queue_backend: Literal["sqs", "kafka", "local"] = "sqs"
kafka_bootstrap_servers: str = "localhost:9092"
kafka_topic: str = "truerag-ingestion"
```

**SQS consumer refactored:**
```python
# sqs_consumer.py — now backend-agnostic
async def run_consumer(backend: QueueBackend, settings: Settings) -> None:
    while True:
        messages = await backend.receive(max_messages=1, wait_seconds=20)
        for msg in messages:
            await _dispatch(msg, backend, settings)
```

---

### CP-6: Docker Compose + Local Development

**New files:**
- `docker-compose.yml`
- `.env.local` (template)
- `docker-compose.override.yml` (dev hot-reload)

**NEW (docker-compose.yml):**
```yaml
version: "3.9"
services:
  mongodb:
    image: mongo:7
    ports: ["27017:27017"]
    volumes: [mongo_data:/data/db]

  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: truerag
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes: [pg_data:/var/lib/postgresql/data]

  localstack:
    image: localstack/localstack:3
    ports: ["4566:4566"]
    environment:
      SERVICES: sqs,s3
      DEFAULT_REGION: us-east-1
    volumes: [localstack_data:/var/lib/localstack]

  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env.local
    depends_on: [mongodb, postgres, localstack]
    volumes: [./app:/app/app]  # hot reload

  worker:
    build: .
    command: python -m app.workers.entrypoint
    env_file: .env.local
    depends_on: [mongodb, localstack]

volumes:
  mongo_data:
  pg_data:
  localstack_data:
```

**NEW (.env.local template):**
```env
APP_ENV=local
QUEUE_BACKEND=sqs
MONGODB_URI=mongodb://localhost:27017
PGVECTOR_DSN=postgresql://postgres:postgres@localhost:5432/truerag
AWS_ENDPOINT_URL=http://localhost:4566
AWS_REGION=us-east-1
SQS_INGESTION_QUEUE_URL=http://localhost:4566/000000000000/truerag-ingestion
S3_DOCUMENT_BUCKET=truerag-documents
```

---

## Section 5: Implementation Handoff

### Scope Classification: MODERATE

Requires backlog reorganization (new stories added to existing epics) + Developer implementation.

### New Stories to Create

| Story ID | Epic | Title | Depends On |
|----------|------|-------|------------|
| 1-11 | Epic 1 (addendum) | Loguru Logging + Request/Response Middleware with Masking | — |
| 1-12 | Epic 1 (addendum) | Generic Service Error Decorator | 1-11 |
| 1-13 | Epic 1 (addendum) | Class-Based Service Architecture + Router Consistency | 1-12 |
| 3-5 | Epic 3 (addendum) | Pluggable Queue Backend (SQS / Kafka / Local) | 1-11 |
| 10-5 | Epic 10 (addendum) | Local Development Docker Compose | 3-5 |

### Recommended Execution Order

```
Week 1:  1-11 (loguru) + 10-5 (docker-compose) in parallel
Week 2:  1-12 (decorator) + 3-5 (queue abstraction) in parallel
Week 3:  1-13 (class-based refactor — largest story, touches all service + router files)
```

### Handoff Responsibilities

| Role | Responsibility |
|------|---------------|
| **Developer agent** | Implement all 5 new stories in sequence above |
| **Developer agent** | Update existing tests to mock service class instances (not module functions) |
| **Developer agent** | Add `loguru` to `pyproject.toml`; remove stdlib logging from `observability.py` |
| **PO** | Update sprint-status.yaml with new story entries |
| **PO** | Mark Epic 1 as `in-progress` (addendum stories) |

### Success Criteria

- [ ] All routers: zero try-except blocks, all routes return service result directly
- [ ] All service functions wrapped with `@service_method` decorator
- [ ] `get_logger` returns loguru bound logger; `JSONFormatter` class deleted
- [ ] Middleware logs every request/response with masked sensitive headers
- [ ] All services are classes; free module-level functions removed
- [ ] `QueueBackend` interface exists; `SQSBackend` and `LocalBackend` implemented
- [ ] `docker-compose up` starts full local stack without AWS credentials
- [ ] Existing test suite passes after refactor

### MVP Impact

**Not affected.** All changes are internal quality improvements. No API contracts, data models, or external-facing behaviour change. Epic 9 observability stories can proceed in parallel — loguru (1-11) should be landed first so 9-x stories use it.

---

## Section 6: sprint-status.yaml Updates Required

After approval, update `_bmad-output/implementation-artifacts/sprint-status.yaml`:

```yaml
# Epic 1: Add addendum stories
epic-1: in-progress  # reopen for addendum
1-11-loguru-logging-request-response-middleware-with-masking: ready-for-dev
1-12-generic-service-error-decorator: ready-for-dev
1-13-class-based-service-architecture-solid-refactor: ready-for-dev

# Epic 3: Add addendum story
epic-3: in-progress  # already in-progress
3-5-pluggable-queue-backend-sqs-kafka-local: ready-for-dev

# Epic 10: Add addendum story
epic-10: in-progress  # already in-progress
10-5-local-development-docker-compose: ready-for-dev
```
