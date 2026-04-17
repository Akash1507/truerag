# Story 1.1: Project Scaffold & Application Skeleton

Status: done

## Story

As an AI Platform Engineer,
I want a fully configured Python project scaffold with FastAPI app factory, directory structure, and code quality tooling,
so that all future implementation has a consistent, lintable, type-checkable foundation.

## Acceptance Criteria

**AC1:** Given a fresh clone of the repository, when `pip install -r requirements-dev.txt` is run, then all dependencies install without error, Ruff linting passes with zero violations, and mypy strict type checking passes with zero errors.

**AC2:** Given the FastAPI application is started with `uvicorn app.main:app`, when the process starts, then the app starts without error, OpenAPI docs are available at `/docs` and `/redoc`, and all routes are prefixed `/v1/`.

**AC3:** Given the project directory structure, when it is inspected, then it matches the architecture spec exactly: `app/api/v1/`, `app/core/`, `app/models/`, `app/services/`, `app/pipelines/`, `app/interfaces/`, `app/providers/`, `app/workers/`, `app/utils/`, `tests/` (mirroring `app/`), `scripts/`, `terraform/`, `docs/adrs/`, `.github/workflows/`.

**AC4:** Given a pre-commit configuration, when `git commit` is run, then Ruff and mypy execute automatically and block the commit on any violation.

## Tasks / Subtasks

- [x] Task 1: Create project metadata and dependency files (AC: 1, 4)
  - [x] 1.1 Create `pyproject.toml` — project metadata, Ruff config (line-length=100, target-version=py311, select=["E","W","F","I","UP","B","SIM"]), mypy config (strict=true, python_version=3.11)
  - [x] 1.2 Create `requirements.txt` — all runtime dependencies pinned to compatible ranges (fastapi, uvicorn[standard], gunicorn, pydantic>=2, pydantic-settings, motor, asyncpg, sqlalchemy[asyncio], aioboto3, presidio-analyzer, presidio-anonymizer, spacy)
  - [x] 1.3 Create `requirements-dev.txt` — test + lint deps (-r requirements.txt, pytest, pytest-asyncio, httpx, ruff, mypy, pre-commit, and all mypy stub packages)
  - [x] 1.4 Create `.env.example` — non-secret local dev vars only (LOG_LEVEL, AWS_REGION, APP_ENV); inline comment: "No secrets here — all credentials via AWS Secrets Manager"
  - [x] 1.5 Create `.gitignore` — Python standard ignores + `.env`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `*.pyc`, `.pytest_cache`
  - [x] 1.6 Create `README.md` — project name, one-line description, quick-start (install + run) instructions

- [x] Task 2: Create complete directory structure with package init stubs (AC: 3)
  - [x] 2.1 Create all `app/` subdirectories: `api/v1/`, `core/`, `models/`, `services/`, `pipelines/ingestion/`, `pipelines/query/`, `interfaces/`, `providers/vector_stores/`, `providers/chunking/`, `providers/embedding/`, `providers/llm/`, `providers/rerankers/`, `providers/cache/`, `workers/`, `utils/`
  - [x] 2.2 Add `__init__.py` to every Python package under `app/` (all dirs above + `app/` itself, `app/api/`, `app/pipelines/`, `app/providers/`)
  - [x] 2.3 Create all `tests/` subdirectories mirroring `app/`: `tests/api/v1/`, `tests/services/`, `tests/pipelines/`, `tests/providers/`, `tests/utils/`, `tests/integration/`
  - [x] 2.4 Add `__init__.py` to every `tests/` package directory
  - [x] 2.5 Create non-Python directories: `scripts/`, `terraform/`, `docs/adrs/`, `.github/workflows/`
  - [x] 2.6 Create placeholder `.gitkeep` in every empty non-Python directory (terraform/, docs/adrs/, scripts/, .github/workflows/) so they appear in git

- [x] Task 3: Create FastAPI application factory in `app/main.py` (AC: 2)
  - [x] 3.1 Create `app/main.py` — FastAPI app factory function `create_app() -> FastAPI` with title="TrueRAG", version="0.1.0", description, docs_url="/docs", redoc_url="/redoc"; include all v1 routers from `app/api/v1`
  - [x] 3.2 Wire lifespan context manager (empty for now — connection setup in Story 1.4); register it on the FastAPI instance
  - [x] 3.3 Create `app/api/v1/__init__.py` — instantiates an `APIRouter(prefix="/v1")` and imports/includes all resource routers; exports the router via `router` module-level variable
  - [x] 3.4 Create stub router files (empty APIRouter, no routes yet) for: `app/api/v1/tenants.py`, `agents.py`, `documents.py`, `query.py`, `eval.py`, `observability.py` — each file defines `router = APIRouter()` at module level

- [x] Task 4: Create `.pre-commit-config.yaml` and validate toolchain (AC: 4)
  - [x] 4.1 Create `.pre-commit-config.yaml` with two hooks: `ruff` (ruff check + ruff format --check) and `mypy` (mypy app/ --strict) using the pinned versions from requirements-dev.txt
  - [x] 4.2 Verify `ruff check app/ tests/` exits 0 on the created scaffold
  - [x] 4.3 Verify `mypy app/ --strict` exits 0 on the created scaffold

- [x] Task 5: Write tests for scaffold (AC: 1, 2)
  - [x] 5.1 Create `tests/conftest.py` — define `app` fixture using `create_app()` and `client` fixture using `httpx.AsyncClient(app=app, base_url="http://test")` with pytest-asyncio
  - [x] 5.2 Create `tests/test_main.py` — test: (a) app instantiates without error, (b) GET /docs returns 200, (c) GET /redoc returns 200, (d) OpenAPI JSON at `/openapi.json` contains `"/v1/"` prefix for every path
  - [x] 5.3 Run `pytest tests/test_main.py -v` and confirm all tests pass

### Review Findings

- [x] [Review][Patch] Ruff pre-commit hook passes an invalid `check` path and fails on clean code [.pre-commit-config.yaml:5]
- [x] [Review][Patch] Pre-commit hooks are not scoped to project code, so vendored assistant files break commits [.pre-commit-config.yaml:1]
- [x] [Review][Patch] Mypy pre-commit hook receives appended filenames and crashes instead of checking `app/` only [.pre-commit-config.yaml:13]
- [x] [Review][Patch] Stub router files are not `ruff format --check` compliant [app/api/v1/agents.py:1]

## Dev Notes

### Critical Architecture Rules (must not violate)

- **No routes in `main.py`** — `main.py` only creates the app and registers the v1 router. All routes live in `app/api/v1/` resource files. [Source: architecture.md#FastAPI Router Registration]
- **All routes prefixed `/v1/`** — enforced by setting `prefix="/v1"` on the top-level router in `app/api/v1/__init__.py` and mounting it via `app.include_router(router)`. [Source: architecture.md#Technical Constraints]
- **No secrets in `.env`** — `.env.example` and any local `.env` are for non-secret config only (log level, region). [Source: architecture.md#Environment & Secrets; project-context.md#Critical Rules]
- **Python 3.11+ strict async** — `asyncio`-first; all I/O will be non-blocking in later stories. [Source: architecture.md#Language & Runtime]
- **`datetime.now(datetime.timezone.UTC)` exclusively** — `datetime.utcnow()` is deprecated in Python 3.12. If any datetime is used in the scaffold, always import `from datetime import datetime, timezone` and use `datetime.now(timezone.UTC)`. [Source: architecture.md#Format Patterns]

### Technology Versions (pinned for compatibility)

| Package | Minimum Version | Notes |
|---|---|---|
| Python | 3.11 | `pyproject.toml` requires-python = ">=3.11" |
| FastAPI | 0.111.0 | Pydantic v2 required; use `pydantic>=2.6.0` |
| Pydantic | 2.6.0 | v2 is required — v1 API is NOT compatible |
| pydantic-settings | 2.2.0 | Settings management for Story 1.2 |
| uvicorn | 0.29.0 | `uvicorn[standard]` for websocket + HTTP/2 support |
| gunicorn | 22.0.0 | Process manager for ECS Fargate production |
| motor | 3.4.0 | MongoDB async driver; PyMongo-compatible API |
| asyncpg | 0.29.0 | PostgreSQL async for pgvector (Epic 4) |
| sqlalchemy | 2.0.0 | `sqlalchemy[asyncio]` for query building |
| aioboto3 | 13.0.0 | Async AWS SDK wrapper |
| presidio-analyzer | 2.2.354 | PII detection — spaCy model `en_core_web_lg` needed |
| presidio-anonymizer | 2.2.354 | PII redaction |
| pytest | 8.0.0 | |
| pytest-asyncio | 0.23.0 | `asyncio_mode = "auto"` in pyproject.toml |
| httpx | 0.27.0 | AsyncClient for FastAPI test client |
| ruff | 0.4.0 | Replaces flake8 + black; configured in pyproject.toml |
| mypy | 1.9.0 | `--strict` mode; configured in pyproject.toml |

### Ruff Configuration (pyproject.toml)

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "SIM"]
ignore = []

[tool.ruff.lint.isort]
known-first-party = ["app"]
```

### Mypy Configuration (pyproject.toml)

```toml
[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = false
plugins = ["pydantic.mypy"]
```

### Pytest Configuration (pyproject.toml)

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### Project Structure Notes

The architecture spec mandates this exact layout — no deviations allowed:

```
truerag/
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── README.md
├── app/
│   ├── main.py
│   ├── api/v1/
│   │   ├── __init__.py         ← defines router = APIRouter(prefix="/v1")
│   │   ├── tenants.py          ← stub: router = APIRouter()
│   │   ├── agents.py
│   │   ├── documents.py
│   │   ├── query.py
│   │   ├── eval.py
│   │   └── observability.py
│   ├── core/                   ← populated in Stories 1.2–1.8
│   ├── models/
│   ├── services/
│   ├── pipelines/ingestion/
│   ├── pipelines/query/
│   ├── interfaces/
│   ├── providers/
│   │   ├── vector_stores/
│   │   ├── chunking/
│   │   ├── embedding/
│   │   ├── llm/
│   │   ├── rerankers/
│   │   └── cache/
│   ├── workers/
│   └── utils/
├── tests/
│   ├── conftest.py
│   ├── test_main.py
│   ├── api/v1/
│   ├── services/
│   ├── pipelines/
│   ├── providers/
│   ├── utils/
│   └── integration/
├── scripts/
├── terraform/
├── docs/adrs/
└── .github/workflows/
```

**CRITICAL:** `app/core/`, `app/models/`, `app/services/`, etc. get their `__init__.py` in this story but their module files in Stories 1.2–1.9. Do NOT create any implementation files beyond what Story 1.1 AC requires.

### Test Pattern

```python
# tests/conftest.py
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import create_app

@pytest.fixture
def app():
    return create_app()

@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
```

```python
# tests/test_main.py
import pytest

async def test_app_starts(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200

async def test_redoc_available(client):
    resp = await client.get("/redoc")
    assert resp.status_code == 200

async def test_all_routes_prefixed_v1(client):
    resp = await client.get("/openapi.json")
    schema = resp.json()
    paths = list(schema.get("paths", {}).keys())
    for path in paths:
        assert path.startswith("/v1/"), f"Route {path!r} not prefixed /v1/"
```

**Note on empty router:** Until resource routes are defined, `/openapi.json` may return `paths: {}`. The test for `/v1/` prefix should guard with `if paths:` or add one minimal route to `observability.py` for the test to be meaningful. Add `GET /v1/health` stub in `app/api/v1/observability.py` returning `{"status": "ok"}` — this also sets up the call site that Story 1.4 will implement fully.

### Anti-Patterns to Avoid

- **Do not** define any routes in `app/main.py` — register `app/api/v1/__init__.py`'s router only
- **Do not** import concrete provider classes anywhere yet — those files don't exist
- **Do not** create `app/core/config.py` content — that's Story 1.2
- **Do not** create `app/core/errors.py` content — that's Story 1.3
- **Do not** use `print()` for any output — that's established as a convention violation in Story 1.2 onwards; for this scaffold no logging calls are needed in `main.py`

### References

- [Source: architecture.md#Foundation & Project Scaffold] — full directory tree, tooling decisions
- [Source: architecture.md#Implementation Patterns & Consistency Rules#Naming Patterns] — PEP 8 naming
- [Source: architecture.md#Implementation Patterns & Consistency Rules#Structure Patterns] — router registration pattern
- [Source: architecture.md#Enforcement Guidelines] — "All agents MUST" rules
- [Source: project-context.md#Technology Stack] — Python 3.11+, FastAPI, async-first
- [Source: project-context.md#Critical Rules] — no TypeScript, config-driven, secrets via Secrets Manager

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- Ruff UP035 violation in `app/main.py`: `from typing import AsyncGenerator` → fixed to `from collections.abc import AsyncGenerator`
- Ruff I001 violation in `app/main.py`: import order fixed (stdlib before third-party)
- Used `uv venv .venv --python 3.11` + `uv pip install -r requirements-dev.txt` for isolated environment

### Completion Notes List

- All 5 tasks and 20 subtasks completed
- Ruff exits 0 on `app/` and `tests/`; mypy --strict exits 0 on 26 source files
- 3 pytest tests pass: test_app_starts, test_redoc_available, test_all_routes_prefixed_v1
- `GET /v1/observability/health` stub added to provide at least one route for the prefix test
- Virtual environment managed via `uv venv .venv --python 3.11`; `.venv/` in `.gitignore`

### File List

- pyproject.toml
- requirements.txt
- requirements-dev.txt
- .env.example
- .gitignore
- README.md
- .pre-commit-config.yaml
- app/__init__.py
- app/main.py
- app/api/__init__.py
- app/api/v1/__init__.py
- app/api/v1/tenants.py
- app/api/v1/agents.py
- app/api/v1/documents.py
- app/api/v1/query.py
- app/api/v1/eval.py
- app/api/v1/observability.py
- app/core/__init__.py
- app/models/__init__.py
- app/services/__init__.py
- app/pipelines/__init__.py
- app/pipelines/ingestion/__init__.py
- app/pipelines/query/__init__.py
- app/interfaces/__init__.py
- app/providers/__init__.py
- app/providers/vector_stores/__init__.py
- app/providers/chunking/__init__.py
- app/providers/embedding/__init__.py
- app/providers/llm/__init__.py
- app/providers/rerankers/__init__.py
- app/providers/cache/__init__.py
- app/workers/__init__.py
- app/utils/__init__.py
- tests/__init__.py
- tests/conftest.py
- tests/test_main.py
- tests/api/__init__.py
- tests/api/v1/__init__.py
- tests/services/__init__.py
- tests/pipelines/__init__.py
- tests/providers/__init__.py
- tests/utils/__init__.py
- tests/integration/__init__.py
- scripts/.gitkeep
- terraform/.gitkeep
- docs/adrs/.gitkeep
- .github/workflows/.gitkeep

### Change Log

- 2026-04-18: Story 1.1 implemented — project scaffold, FastAPI app factory, full directory structure, toolchain validation, tests (3 passing)
