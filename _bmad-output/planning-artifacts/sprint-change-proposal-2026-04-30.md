# Sprint Change Proposal: Beanie ODM + DAO Layer + DynamoDB Removal

**Date:** 2026-04-30  
**Requested by:** Akash  
**Scope:** MODERATE — Developer agent implementation  
**Status:** APPROVED

---

## Section 1: Issue Summary

Three architectural deficiencies identified via user review after Epic 3 completion:

1. **DynamoDB for ingestion job tracking** — `dynamodb_jobs_table` stores and queries job status despite MongoDB being the primary store. This introduces an unnecessary AWS dependency, requires reserved-word expression workarounds (`ExpressionAttributeNames`), and creates dual-store status logic (`get_document_status` queries MongoDB first, DynamoDB second).

2. **Business logic in routers** — Every router does `db = request.app.state.motor_client[settings.mongodb_database]` (infrastructure concern), builds response objects with fallback logic (e.g. `rate_limit_rpm` default in `tenants.py`), and some contain auth cross-checks (e.g. tenant ID guard in `agents.py`). All of this belongs in the service layer.

3. **No ODM / DAO layer** — Services accept `db: AsyncIOMotorDatabase` and operate on raw dicts (`db["tenants"].find_one(...)`, `AgentDocument(**{k: doc[k] for k in ...})`). Beanie is not used despite being in the intended stack. No `BaseDAO` abstraction means collection access patterns are duplicated across every service.

---

## Section 2: Impact Analysis

### Epic Impact

| Epic | Impact |
|------|--------|
| Epic 1 (Platform Foundation) | New story added: `1-10-beanie-odm-dao-layer-and-dynamodb-removal` |
| Epics 2–3 (done) | Refactored — behavior preserved, no API contract changes |
| Epics 4–10 (backlog) | Benefit from DAO layer; no scope changes required |

### Story Impact

- Stories 1.4, 2.1–2.6, 3.1–3.3 (all done): refactored but functionally identical from API perspective
- New story: **1-10** (see Section 4)

### Artifact Conflicts

| Artifact | Change Required |
|----------|----------------|
| `architecture.md` — D1 MongoDB Collections | Add `ingestion_jobs` collection |
| `architecture.md` — D2 DynamoDB Tables | Remove `truerag-ingestion-jobs`; note `truerag-audit-log` remains |
| `architecture.md` — D3 Async Driver Stack | Add Beanie as ODM layer over Motor |
| `architecture.md` — Project Structure | Add `app/db/` directory |
| `architecture.md` — Technical Constraints | Remove DynamoDB for jobs; keep for audit log |
| `app/core/config.py` | Remove `dynamodb_jobs_table` setting |
| `app/api/v1/observability.py` | Remove DynamoDB readiness check |
| `pyproject.toml` | Add `beanie` dependency |

### Technical Impact

**Files modified:**
- `app/core/config.py` — remove `dynamodb_jobs_table`
- `app/main.py` — add `init_beanie(...)`, remove DynamoDB health setup
- `app/api/v1/observability.py` — remove DynamoDB readiness check
- `app/api/v1/tenants.py` — strip infrastructure setup + response building → service
- `app/api/v1/agents.py` — strip infrastructure setup + tenant ID check → service
- `app/api/v1/documents.py` — strip `db`/`aws_session` extraction
- `app/core/auth.py` — use `TenantDAO` instead of raw Motor
- `app/services/tenant_service.py` — use `TenantDAO`, no `db` param
- `app/services/agent_service.py` — use `AgentDAO` + `DocumentDAO`, no `db` param, remove DynamoDB calls
- `app/services/ingestion_service.py` — use `DocumentDAO` + `IngestionJobDAO`, replace all DynamoDB with MongoDB
- `app/models/tenant.py` — add Beanie `Document` subclass
- `app/models/agent.py` — add Beanie `Document` subclass
- `app/models/document.py` — add Beanie `Document` subclass for `DocumentRecord`

**Files created:**
- `app/models/ingestion_job.py` — Beanie Document replacing DynamoDB jobs table
- `app/db/__init__.py`
- `app/db/base_dao.py` — `BaseDAO[T]` with `find`, `find_one`, `insert`, `insert_one`, `update`, `aggregate`, `pipeline`
- `app/db/dao/__init__.py`
- `app/db/dao/tenant_dao.py`
- `app/db/dao/agent_dao.py`
- `app/db/dao/document_dao.py`
- `app/db/dao/ingestion_job_dao.py`

**Tests updated:** All tests touching services, routers, and the observability endpoint.

---

## Section 3: Recommended Approach

**Option 1 — Direct Adjustment.** Implement as a single refactor story (`1-10`) before continuing with Epic 4.

**Rationale:**
- No API contract changes (same endpoints, same request/response shapes)
- Well-defined scope — all changes are within `app/` directory
- Eliminates the DynamoDB dependency from the ingestion path before Epic 4 adds more services on top of this layer
- Beanie + DAO layer established now means Epics 4–10 build on clean foundation
- Risk is medium — touches every layer but behavior is preserved

**Effort:** High (16 task items across 8+ files)  
**Risk:** Medium (all changes are refactors with identical external behavior)  
**Timeline impact:** One sprint story delay before Epic 4 begins

---

## Section 4: Detailed Change Proposals

### New Story: `1-10-beanie-odm-dao-layer-and-dynamodb-removal`

**Tasks:**

1. Add `beanie` to `pyproject.toml`
2. Create `app/models/ingestion_job.py` — Beanie `Document` with fields: `job_id`, `document_id`, `tenant_id`, `status`, `error_reason`, `created_at`
3. Convert `app/models/tenant.py` — `TenantDocument` extends `beanie.Document`; `Settings.name = "tenants"`
4. Convert `app/models/agent.py` — `AgentDocument` extends `beanie.Document`; `Settings.name = "agents"`
5. Convert `app/models/document.py` — `DocumentRecord` extends `beanie.Document`; `Settings.name = "documents"`
6. Create `app/db/base_dao.py` — `BaseDAO[T]` generic class exposing: `find`, `find_one`, `insert`, `insert_one`, `update`, `aggregate`, `pipeline`
7. Create `app/db/dao/tenant_dao.py`, `agent_dao.py`, `document_dao.py`, `ingestion_job_dao.py` — each extends `BaseDAO`
8. Refactor `app/services/tenant_service.py` — use `TenantDAO` singleton, remove `db: AsyncIOMotorDatabase` param
9. Refactor `app/services/agent_service.py` — use `AgentDAO` + `DocumentDAO`, remove `db` param, remove all DynamoDB calls (job deletion moves to `IngestionJobDAO.delete`)
10. Refactor `app/services/ingestion_service.py` — use `DocumentDAO` + `IngestionJobDAO`, replace `dynamo.put_item` / `get_item` / `update_item` with Beanie operations
11. Clean `app/api/v1/tenants.py` — routers only do auth + call service + return response; response shaping to service
12. Clean `app/api/v1/agents.py` — move tenant ID cross-check to `agent_service.create_agent`
13. Clean `app/api/v1/documents.py` — remove `db`/`aws_session` extraction from route handlers
14. Update `app/core/auth.py` — replace raw Motor lookup with `TenantDAO.find_one`
15. Update `app/main.py` — call `init_beanie(database=db, document_models=[...])` at startup; remove DynamoDB session dependency
16. Update `app/core/config.py` — remove `dynamodb_jobs_table`
17. Update `app/api/v1/observability.py` — remove DynamoDB readiness check from `/ready` endpoint
18. Update all affected tests

### Architecture Doc Changes (D1, D2, D3)

**D1 — Add `ingestion_jobs` collection:**

```
OLD (no entry for ingestion_jobs):
| Collection | Purpose | Key Fields |
| `tenants`  | ...     | ...        |
| `agents`   | ...     | ...        |
| `eval_datasets` | ... | ...      |
| `eval_experiments` | ... | ...   |
| `semantic_cache` | ... | ...     |

NEW:
| `ingestion_jobs` | Async ingestion job status, replaces DynamoDB jobs table | `job_id`, `document_id`, `tenant_id`, `status`, `error_reason`, `created_at` |
```

**D2 — Remove `truerag-ingestion-jobs`:**

```
OLD:
- `truerag-audit-log` — partition key: tenant_id, sort key: timestamp#query_hash
- `truerag-ingestion-jobs` — partition key: job_id (polled by job ID directly)

NEW:
- `truerag-audit-log` — partition key: tenant_id, sort key: timestamp#query_hash
  (ingestion job status moved to MongoDB `ingestion_jobs` collection)
```

**D3 — Add Beanie to async driver stack:**

```
OLD:
| MongoDB | motor | Async MongoDB driver; PyMongo-compatible API |

NEW:
| MongoDB | motor + beanie | motor as async driver; Beanie as ODM layer for Document models and DAO operations |
```

**New section — DAO Layer:**

```
## DAO Layer

BaseDAO[T] in app/db/base_dao.py provides typed collection access:
- find(query, sort, limit) -> list[T]
- find_one(query) -> T | None
- insert(documents) -> list[T]
- insert_one(document) -> T
- update(query, update_dict) -> None
- aggregate(pipeline) -> list[dict]
- pipeline(pipeline) -> list[dict]  # alias for aggregate with different semantic intent

Per-collection DAOs in app/db/dao/:
- TenantDAO extends BaseDAO[TenantDocument]
- AgentDAO extends BaseDAO[AgentDocument]
- DocumentDAO extends BaseDAO[DocumentRecord]
- IngestionJobDAO extends BaseDAO[IngestionJob]

Services receive DAO instances via injection. No raw Motor collection access outside of app/db/.
```

---

## Section 5: Implementation Handoff

**Scope classification:** MODERATE  
**Handoff to:** Developer agent (`/bmad-agent-dev` or `/bmad-dev-story`)  
**Story file:** Create `_bmad-output/implementation-artifacts/1-10-beanie-odm-dao-layer-and-dynamodb-removal.md`

**Success criteria:**
- All tests pass with no mocks for DynamoDB
- No `motor.motor_asyncio.AsyncIOMotorDatabase` in any router file
- No `aioboto3` DynamoDB client calls outside of S3/SQS usage
- No `db["collection"]` raw access outside of `app/db/`
- `/ready` endpoint returns without DynamoDB check
- `config.py` has no `dynamodb_jobs_table` field
- All service functions have no `db: AsyncIOMotorDatabase` parameter
