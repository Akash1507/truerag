# Story 1-13: Class-Based Service Architecture + Router Consistency (SOLID Refactor)

**Epic:** 1 — Platform Foundation & Security Baseline (addendum)
**Status:** review
**Depends on:** 1-11 (loguru), 1-12 (service_method decorator)
**Sprint Change Proposal:** sprint-change-proposal-2026-05-07.md

## User Story

As an AI Platform Engineer,
I want all service modules refactored to cohesive classes with injected dependencies, and all routers simplified to direct service delegation,
So that the codebase follows SOLID principles, has clear separation of concerns, and routers contain zero error-handling or response-mapping logic.

## Background

Current state — two problems:

**Problem A — Free functions:** Every service module (`agent_service.py`, `ingestion_service.py`, `tenant_service.py`, `eval_service.py`, `query_service.py`, `metrics_service.py`, `audit_service.py`) consists of module-level free functions. DAOs and loggers are imported at module top — tight coupling, hard to mock, no cohesion boundary.

**Problem B — Router inconsistency:** Three patterns coexist across routers:
1. `return ServiceResponse(**service_result.model_dump())` — manual model re-mapping
2. `try: ... except ValueError: raise InvalidCursorError(...)` — error translation in router
3. `return await service.method(...)` — clean

Target: Pattern 3 only. Services own typing and error translation (via `@service_method`). Routers own HTTP binding only.

## Acceptance Criteria

**Given** any router endpoint
**When** inspected
**Then** zero `try-except` blocks; zero manual `ResponseModel(**doc.model_dump())` constructions; all routes delegate directly: `return await <service>.<method>(...)`

**Given** any service class
**When** inspected
**Then** is a class (not a module of free functions); has `__init__` accepting DAO/dependency objects; all public async methods decorated with `@service_method`; returns correctly-typed response models (not raw DB documents)

**Given** a service module
**When** imported
**Then** a module-level singleton instance is exported (e.g. `agent_service = AgentService(dao=agent_dao)`) enabling backward-compatible import in routers during transition

**Given** existing tests for service functions
**When** tests run after refactor
**Then** tests updated to instantiate service class with mock DAO; all pass

**Given** mypy strict runs on all modified files
**When** check completes
**Then** zero type errors

## Services to Refactor

| Module | Class Name | Key Dependencies |
|--------|-----------|-----------------|
| `agent_service.py` | `AgentService` | `AgentDAO`, `VectorStore` (via `get_vector_store`) |
| `ingestion_service.py` | `IngestionService` | `DocumentDAO`, `IngestionJobDAO`, `AgentService` |
| `tenant_service.py` | `TenantService` | `TenantDAO` |
| `eval_service.py` | `EvalService` | `EvalDatasetDAO`, `EvalExperimentDAO`, `AgentService`, `QueryService` |
| `query_service.py` | `QueryService` | `AgentDAO`, `VectorStore`, pipeline components |
| `metrics_service.py` | `MetricsService` | `QueryCostDAO` |
| `audit_service.py` | `AuditService` | AWS session (injected at call time) |

## Implementation Pattern

### Service class (agent_service.py example)

```python
from loguru import logger
from app.core.decorators import service_method
from app.core.errors import AgentAlreadyExistsError, AgentNotFoundError, ForbiddenError
from app.db.dao.agent_dao import AgentDAO, agent_dao
from app.models.agent import (
    AgentCreateRequest, AgentCreateResponse,
    AgentListResponse, AgentConfigUpdateRequest, AgentUpdateResponse,
)
from app.utils.pagination import DEFAULT_PAGE_SIZE, decode_cursor, encode_cursor


class AgentService:
    def __init__(self, dao: AgentDAO) -> None:
        self._dao = dao

    @service_method("create_agent")
    async def create(self, body: AgentCreateRequest, tenant_id: str) -> AgentCreateResponse:
        ...  # existing logic moved here; returns AgentCreateResponse directly

    @service_method("list_agents")
    async def list(
        self, tenant_id: str, cursor: str | None, limit: int = DEFAULT_PAGE_SIZE
    ) -> AgentListResponse:
        ...  # ValueError from decode_cursor auto-handled by decorator

    @service_method("get_agent")
    async def get(self, agent_id: str, tenant_id: str) -> AgentCreateResponse:
        ...

    @service_method("update_agent_config")
    async def update_config(
        self, agent_id: str, tenant_id: str, body: AgentConfigUpdateRequest
    ) -> AgentUpdateResponse:
        ...

    @service_method("delete_agent")
    async def delete(self, agent_id: str, tenant_id: str, aws_session, settings) -> None:
        ...


# Module-level singleton — routers import this
agent_service = AgentService(dao=agent_dao)
```

### Router (agents.py example — final form)

```python
from fastapi import APIRouter, Depends, Query, Request, status
from app.core.auth import get_current_tenant
from app.core.config import get_settings
from app.models.agent import AgentCreateRequest, AgentConfigUpdateRequest
from app.models.tenant import TenantDocument
from app.services.agent_service import agent_service
from app.utils.pagination import DEFAULT_PAGE_SIZE

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent_route(
    body: AgentCreateRequest,
    caller: TenantDocument = Depends(get_current_tenant),
):
    return await agent_service.create(body, caller.tenant_id)


@router.get("")
async def list_agents_route(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
    caller: TenantDocument = Depends(get_current_tenant),
):
    return await agent_service.list(caller.tenant_id, cursor, limit)


@router.get("/{agent_id}")
async def get_agent_route(agent_id: str, caller: TenantDocument = Depends(get_current_tenant)):
    return await agent_service.get(agent_id, caller.tenant_id)


@router.patch("/{agent_id}/config")
async def update_agent_config_route(
    agent_id: str,
    body: AgentConfigUpdateRequest,
    caller: TenantDocument = Depends(get_current_tenant),
):
    return await agent_service.update_config(agent_id, caller.tenant_id, body)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_route(
    agent_id: str,
    request: Request,
    caller: TenantDocument = Depends(get_current_tenant),
):
    await agent_service.delete(agent_id, caller.tenant_id, request.app.state.aws_session, get_settings())
```

Note: `response_model=` annotation removed from router decorators — FastAPI infers from return type of service method. Alternatively keep `response_model=` for OpenAPI docs clarity; in that case service returns the exact typed model.

## Routers to Update

| Router | try-except to remove | Manual mapping to remove |
|--------|---------------------|--------------------------|
| `agents.py` | `list_agents_route` ValueError | `create_agent_route`, `get_agent_route`, `update_agent_config_route`, `list_agents_route` |
| `documents.py` | `list_documents_route` ValueError | none (already clean) |
| `tenants.py` | `list_tenants_route` ValueError | `register_tenant` (manual field-by-field construction) |
| `eval.py` | `get_eval_history` ValueError | `create_eval_dataset`, `run_eval`, `get_eval_history` |
| `query.py` | none | none (already clean) |
| `observability.py` | existing try-except blocks | none |

## Test Updates Required

All tests currently mocking `agent_service.create_agent` (free function) must be updated to mock `agent_service.create` (method on class instance). Pattern:

```python
# OLD
mocker.patch("app.services.agent_service.create_agent", return_value=mock_doc)

# NEW
mocker.patch.object(agent_service, "create", return_value=mock_response)
```

## Definition of Done

- [x] All 7 service modules are classes with `@service_method` decorators
- [x] Module-level singleton exported from each service module
- [x] All routers: zero try-except, zero manual `**model.model_dump()` mapping
- [x] Service methods return response models (not raw DB documents)
- [x] All existing tests updated and passing
- [x] mypy strict passes on all modified files
- [x] No import cycle introduced
