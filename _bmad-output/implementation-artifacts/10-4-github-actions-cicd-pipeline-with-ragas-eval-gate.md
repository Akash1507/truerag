# Story 10.4: GitHub Actions CI-CD Pipeline with RAGAS Eval Gate

Status: review

## Story

As an AI Platform Engineer,
I want a full CI-CD pipeline that runs tests and type checks on every PR, and blocks deployments when RAGAS scores fall below the configured threshold against a dedicated eval agent on the production deployment,
so that code quality and retrieval quality are both enforced automatically before any change reaches users (NFR22).

## Acceptance Criteria

1. **Given** a pull request is opened against `main` **When** `ci.yml` runs **Then** Ruff linting, mypy strict type checking, and the full pytest suite (unit + integration) must all pass; a failing check blocks merge.

2. **Given** `deploy.yml` triggers on merge to `main` **When** it executes **Then** it builds a Docker image, pushes to ECR `truerag`, deploys to ECS via rolling deployment (minimum healthy percent preserving old tasks during rollout), then runs `POST /v1/agents/{eval_agent_id}/eval/run` against a dedicated eval agent on the production deployment before the rollout completes.

3. **Given** no separate staging environment in v1 **When** the RAGAS eval gate runs **Then** it targets a dedicated eval agent (`eval_agent_id`) provisioned on the production deployment; this agent has a stable golden dataset and indexed documents used solely for CI-CD quality gates; the approach is documented in `docs/adrs/`.

4. **Given** the RAGAS eval gate returns a `faithfulness` score below the configured threshold **When** `deploy.yml` processes the result **Then** the ECS rolling deployment is halted; old tasks continue serving traffic; workflow exits with non-zero status visible in GitHub Actions run summary.

5. **Given** the eval run exceeds 20 questions (async path) **When** the pipeline waits for results **Then** `deploy.yml` polls `GET /v1/agents/{eval_agent_id}/eval/history` for the `run_id` with configurable timeout (default 10 minutes); if timeout exceeded, deployment is halted.

## Tasks / Subtasks

- [x] Task 1: Create `ci.yml` workflow (AC: 1)
  - [x] Trigger: `on: pull_request: branches: [main]`
  - [x] Job: `quality-checks`
  - [x] Step: Checkout code
  - [x] Step: Setup Python 3.11 with `actions/setup-python`
  - [x] Step: Install dependencies via `pip install -r requirements.txt -r requirements-dev.txt`
  - [x] Step: Run Ruff lint — `ruff check .`
  - [x] Step: Run Ruff format check — `ruff format --check .`
  - [x] Step: Run mypy strict — `mypy --strict app/`
  - [x] Step: Run pytest unit tests — `pytest tests/ -m "not integration" -v`
  - [x] Step: Run pytest integration tests — `pytest tests/ -m integration -v` (may require service containers)
  - [x] Configure test service containers (PostgreSQL with pgvector, MongoDB) for integration tests if needed

- [x] Task 2: Create `deploy.yml` workflow (AC: 2, 3, 4, 5)
  - [x] Trigger: `on: push: branches: [main]`
  - [x] Concurrency group to prevent parallel deployments: `concurrency: group: deploy-prod, cancel-in-progress: false`
  - [x] Job: `deploy`
  - [x] Permissions: `id-token: write`, `contents: read` (for OIDC AWS auth)

- [x] Task 3: Docker build + ECR push step (AC: 2)
  - [x] Authenticate to AWS via OIDC (`aws-actions/configure-aws-credentials`)
  - [x] Login to ECR (`aws-actions/amazon-ecr-login`)
  - [x] Build Docker image with tag: `$ECR_REGISTRY/truerag:$GITHUB_SHA` and `latest`
  - [x] Push both tags to ECR

- [x] Task 4: Dockerfile (AC: 2)
  - [x] Create `Dockerfile` at repo root if not already present
  - [x] Base: `python:3.11-slim`
  - [x] Install system deps: `libpq-dev` (asyncpg needs it)
  - [x] Copy and install `requirements.txt`
  - [x] Copy `app/` directory
  - [x] Default CMD: `["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "app.main:app", "--bind", "0.0.0.0:8000"]`
  - [x] Worker entry point override via ECS task definition command (not in Dockerfile)
  - [x] `.dockerignore`: exclude `tests/`, `terraform/`, `.github/`, `*.md`, `.env*`, `__pycache__`

- [x] Task 5: ECS rolling deployment step (AC: 2, 4)
  - [x] Update ECS service `truerag-api` with new image: `aws ecs update-service --cluster truerag --service truerag-api --force-new-deployment`
  - [x] Update ECS service `truerag-worker` with new image
  - [x] Wait for API service to reach steady state: `aws ecs wait services-stable --cluster truerag --services truerag-api`
  - [x] Timeout for wait: 10 minutes

- [x] Task 6: RAGAS eval gate step — trigger eval run (AC: 2, 3)
  - [x] Read `EVAL_AGENT_ID` from GitHub Actions secret (provisioned out-of-band)
  - [x] Read `TRUERAG_API_URL` from GitHub Actions secret (production API endpoint)
  - [x] Read `TRUERAG_API_KEY` from GitHub Actions secret (eval agent's tenant API key)
  - [x] POST to `$TRUERAG_API_URL/v1/agents/$EVAL_AGENT_ID/eval/run`
  - [x] Capture `run_id` from response body

- [x] Task 7: RAGAS eval gate step — poll for results (AC: 4, 5)
  - [x] Poll `GET $TRUERAG_API_URL/v1/agents/$EVAL_AGENT_ID/eval/history?run_id=$RUN_ID`
  - [x] Poll interval: 30 seconds
  - [x] Timeout: `EVAL_TIMEOUT_MINUTES` variable (default 10 minutes = 20 polls)
  - [x] Exit with failure if timeout exceeded
  - [x] Extract `faithfulness` score from response

- [x] Task 8: RAGAS eval gate step — threshold check (AC: 4)
  - [x] Compare `faithfulness` score to `RAGAS_FAITHFULNESS_THRESHOLD` secret/variable (default 0.6)
  - [x] If score >= threshold: log success, continue
  - [x] If score < threshold: log failure with score + threshold values, `exit 1`
  - [x] On failure: optionally trigger ECS service rollback (`aws ecs update-service --task-definition <previous>`) — document if implemented or deferred

- [x] Task 9: GitHub Actions secrets documentation (AC: 3)
  - [x] Document in `docs/adrs/adr-019-cicd-eval-gate-strategy.md`:
    - Required GitHub Actions secrets: `AWS_ROLE_ARN`, `ECR_REGISTRY`, `TRUERAG_API_URL`, `TRUERAG_API_KEY`, `EVAL_AGENT_ID`, `RAGAS_FAITHFULNESS_THRESHOLD`
    - Rationale for dedicated prod eval agent (no staging env in v1)
    - Eval agent provisioning steps (seed script or manual API calls)
    - Rollback strategy: manual re-trigger vs automated rollback

- [x] Task 10: AWS OIDC IAM role for GitHub Actions (AC: 2)
  - [x] Add `terraform/modules/github_oidc/` or inline in prod environment:
    - IAM OIDC provider for `token.actions.githubusercontent.com`
    - IAM role `truerag-github-actions` with trust policy for this repo's main branch
    - Permissions: ECR push, ECS update-service, ECS register-task-definition, ECS describe-services, ECS wait

## Dev Notes

### Critical Architecture Constraints

- **RAGAS eval gate is blocking** (NFR22): The deployment workflow MUST NOT complete successfully if the RAGAS gate fails. `exit 1` in the eval check step causes the job to fail, which is visible in the GitHub Actions summary and blocks any dependent jobs.
- **No staging environment in v1**: The eval gate runs against a dedicated eval agent on the production deployment. This is an explicit architectural decision. The ADR must document the rationale and risk mitigation (stable golden dataset, dedicated eval-only agent).
- **Async eval path**: When the eval dataset has > 20 questions, `POST /eval/run` returns immediately with a `run_id` and the eval runs asynchronously. The pipeline MUST poll `GET /eval/history` — do NOT assume synchronous completion.
- **Eval history polling endpoint**: check the actual response shape in `app/api/v1/eval.py` before writing the polling script. The `run_id` field name in the history response must be verified.
- **Rolling deployment preserves old tasks**: `minimum_healthy_percent = 100` in ECS means old tasks stay until new tasks are healthy. The eval gate runs AFTER new tasks are healthy but uses the same production endpoint — this is the intended design.
- **Concurrency**: Only one deployment runs at a time. Use GitHub Actions `concurrency` with `cancel-in-progress: false` to queue, not cancel, concurrent deploys.

### CI Workflow Service Containers

Integration tests require PostgreSQL (pgvector) and MongoDB. Use GitHub Actions service containers:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg15
    env:
      POSTGRES_PASSWORD: test
      POSTGRES_DB: truerag_test
    ports: ["5432:5432"]
  mongodb:
    image: mongo:7
    ports: ["27017:27017"]
```

Tests should use environment variables pointing to these containers (not production services).

### Dockerfile Pattern

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y libpq-dev curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# API default command — worker overrides via ECS task definition
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "app.main:app", "--bind", "0.0.0.0:8000"]
```

### RAGAS Gate Script Pattern

Implement as a Python script `scripts/eval_gate.py` or inline bash in the workflow:

```python
# scripts/eval_gate.py
import os, time, sys, requests

api_url = os.environ["TRUERAG_API_URL"]
agent_id = os.environ["EVAL_AGENT_ID"]
api_key = os.environ["TRUERAG_API_KEY"]
threshold = float(os.environ.get("RAGAS_FAITHFULNESS_THRESHOLD", "0.6"))
timeout_minutes = int(os.environ.get("EVAL_TIMEOUT_MINUTES", "10"))

headers = {"X-API-Key": api_key}

# Trigger eval run
resp = requests.post(f"{api_url}/v1/agents/{agent_id}/eval/run", headers=headers)
resp.raise_for_status()
run_id = resp.json()["run_id"]

# Poll for completion
deadline = time.time() + timeout_minutes * 60
while time.time() < deadline:
    time.sleep(30)
    history = requests.get(f"{api_url}/v1/agents/{agent_id}/eval/history", headers=headers, params={"run_id": run_id})
    history.raise_for_status()
    result = history.json()
    if result.get("status") == "completed":
        score = result["scores"]["faithfulness"]
        print(f"RAGAS faithfulness: {score} (threshold: {threshold})")
        sys.exit(0 if score >= threshold else 1)

print(f"Eval gate timed out after {timeout_minutes} minutes")
sys.exit(1)
```

Note: Verify exact response field names (`run_id`, `scores.faithfulness`, `status`) against `app/api/v1/eval.py` and `app/models/eval.py` before finalising.

### GitHub Actions Secrets Required

| Secret | Description |
|---|---|
| `AWS_ROLE_ARN` | IAM role for OIDC auth (from terraform) |
| `ECR_REGISTRY` | ECR registry URL |
| `TRUERAG_API_URL` | Production API URL (e.g., `https://api.truerag.example.com`) |
| `TRUERAG_API_KEY` | API key for eval tenant |
| `EVAL_AGENT_ID` | MongoDB ID of the dedicated eval agent |
| `RAGAS_FAITHFULNESS_THRESHOLD` | Default `0.6` (matches NFR4) |

### File Structure

```
.github/
└── workflows/
    ├── ci.yml       # PR checks: ruff, mypy, pytest
    └── deploy.yml   # Build → push ECR → deploy ECS → RAGAS gate

Dockerfile           # At repo root
.dockerignore        # At repo root
scripts/
└── eval_gate.py     # RAGAS gate polling script (called from deploy.yml)
docs/adrs/
└── adr-019-cicd-eval-gate-strategy.md
```

### Testing the Workflow Locally

Developers can run the quality checks locally:
```bash
ruff check .
ruff format --check .
mypy --strict app/
pytest tests/ -m "not integration" -v
```

These must all pass before pushing to PR.

### Project Structure Notes

- `.github/workflows/` exists with only `.gitkeep` — add `ci.yml` and `deploy.yml`
- `scripts/` already has `run_eval.py` for local eval runs — `eval_gate.py` is a CI-specific variant
- `Dockerfile` likely does not exist yet — create at repo root
- Do NOT use `--no-verify` or any hook bypass in CI steps

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Project Structure] — `.github/workflows/ci.yml` and `deploy.yml` filenames confirmed
- [Source: _bmad-output/planning-artifacts/architecture.md#Requirements Coverage] — NFR22: "RAGAS eval gate | deploy.yml blocks deployment below configured threshold"
- [Source: _bmad-output/planning-artifacts/architecture.md#Code Quality section] — Ruff, mypy strict, pytest-asyncio
- [Source: _bmad-output/planning-artifacts/epics.md#Story 10.4 AC] — exact workflow requirements including async polling
- [Source: _bmad-output/planning-artifacts/epics.md#NonFunctional Requirements] — NFR22 definition
- [Source: _bmad-output/planning-artifacts/architecture.md#Technical Constraints] — Python 3.11+, Gunicorn on ECS

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- Added CI workflow: `.github/workflows/ci.yml`
- Added deploy workflow: `.github/workflows/deploy.yml`
- Implemented eval gate script + tests: `scripts/eval_gate.py`, `tests/scripts/test_eval_gate.py`
- Added Docker assets: `Dockerfile`, `.dockerignore`
- Added ADR-019 and Terraform OIDC module
- Validation commands run from local environment and `.venv`

### Completion Notes List

- Implemented PR quality gate workflow with Ruff, Ruff format check, mypy strict, and split pytest unit/integration jobs with PostgreSQL+MongoDB service containers.
- Implemented deploy workflow with OIDC auth, ECR build/push, ECS task-definition image updates, rolling service deploy, service-stable waits, and blocking eval gate execution.
- Implemented `scripts/eval_gate.py` for both synchronous and asynchronous eval paths, including timeout and faithfulness threshold gating.
- Documented production dedicated eval-agent strategy, required secrets, provisioning, and rollback posture in ADR-019.
- Added Terraform module for GitHub OIDC provider and `truerag-github-actions` IAM role/policy for ECR and ECS deployment operations.
- Automated rollback is deferred; fail-fast gate behavior is documented per story requirement.

### File List

- .github/workflows/ci.yml
- .github/workflows/deploy.yml
- Dockerfile
- .dockerignore
- scripts/__init__.py
- scripts/eval_gate.py
- tests/scripts/test_eval_gate.py
- docs/adrs/adr-019-cicd-eval-gate-strategy.md
- terraform/modules/github_oidc/main.tf
- terraform/modules/github_oidc/variables.tf
- terraform/modules/github_oidc/outputs.tf
- requirements.txt
