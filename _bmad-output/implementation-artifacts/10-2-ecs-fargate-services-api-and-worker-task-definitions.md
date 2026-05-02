# Story 10.2: ECS Fargate Services — API & Worker Task Definitions

Status: ready-for-dev

## Story

As an AI Platform Engineer,
I want the `truerag-api` and `truerag-worker` ECS Fargate services deployed as independent task definitions,
so that the API and ingestion worker scale independently and async separation is enforced architecturally (NFR13, NFR14).

## Acceptance Criteria

1. **Given** `terraform/modules/ecs/` **When** applied **Then** two independent ECS services exist: `truerag-api` (FastAPI + Uvicorn + Gunicorn, scales on CPU/request count behind an ALB) and `truerag-worker` (SQS consumer, scales on SQS queue depth via Application Auto Scaling); the two services share no in-process state and run in separate task definitions.

2. **Given** the `truerag-api` service **When** it starts **Then** `GET /v1/ready` returns HTTP 200 before the ALB target group marks the task healthy and starts routing traffic.

3. **Given** the `truerag-worker` service **When** SQS queue depth exceeds the configured threshold **Then** Application Auto Scaling adds worker tasks; when queue depth returns to baseline, tasks scale back down; ingestion load never impacts `truerag-api` CPU or memory.

4. **Given** CloudWatch Logs configured via ECS `awslogs` log driver **When** either service emits structured JSON log entries **Then** they stream to CloudWatch Log Groups `/truerag/api` and `/truerag/worker` respectively and are queryable via CloudWatch Logs Insights.

## Tasks / Subtasks

- [ ] Task 1: Create `terraform/modules/ecs/` module structure (AC: 1)
  - [ ] `terraform/modules/ecs/main.tf` — ECS cluster, task definitions, services
  - [ ] `terraform/modules/ecs/variables.tf` — parameterise image URI, CPU/memory, desired count, SQS thresholds
  - [ ] `terraform/modules/ecs/outputs.tf` — service names, task role ARN

- [ ] Task 2: ECS cluster (AC: 1)
  - [ ] Create ECS cluster `truerag` with container insights enabled
  - [ ] No EC2 capacity providers — Fargate only

- [ ] Task 3: IAM roles (AC: 1, 4)
  - [ ] `truerag-task-execution-role`: AmazonECSTaskExecutionRolePolicy + permission to pull from ECR + read CloudWatch Logs
  - [ ] `truerag-task-role` (shared): permission to read Secrets Manager ARNs (from Story 10.1 secrets module outputs), S3 read/write, SQS send/receive/delete, DynamoDB read/write on both tables, CloudWatch PutMetricData
  - [ ] Worker task role needs SQS receive/delete/change-visibility on ingestion queue; API task role needs SQS send only
  - [ ] Principle of least privilege — separate inline policies per service if scopes differ

- [ ] Task 4: `truerag-api` task definition (AC: 1, 2, 4)
  - [ ] Container: `truerag-api`, image from ECR `truerag:latest` (parameterisable)
  - [ ] Command: `["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "app.main:app", "--bind", "0.0.0.0:8000"]`
  - [ ] Port mapping: 8000/tcp
  - [ ] CPU: 1024, Memory: 2048 (prod) — override via variable
  - [ ] Environment variables: non-secret (log level, region, env name) from task definition
  - [ ] Secrets: all credentials injected from Secrets Manager via `secrets` block (NOT environment vars) using ARNs from Story 10.1 outputs
  - [ ] Log driver: `awslogs`, log group `/truerag/api`, region `us-east-1`, stream prefix `api`
  - [ ] Health check: `["CMD-SHELL", "curl -f http://localhost:8000/v1/ready || exit 1"]` with 30s interval, 3 retries, 60s start period

- [ ] Task 5: `truerag-api` ECS service (AC: 1, 2)
  - [ ] Service `truerag-api` using Fargate launch type
  - [ ] Desired count: 2 (prod), 1 (dev) — variable
  - [ ] Load balancer integration: ALB target group from networking module (Story 10.1), container port 8000
  - [ ] Deployment: rolling update, minimum healthy percent 100, maximum percent 200
  - [ ] Service discovery not required for v1
  - [ ] `wait_for_steady_state = true` to block Terraform until service is healthy

- [ ] Task 6: `truerag-worker` task definition (AC: 1, 3, 4)
  - [ ] Container: `truerag-worker`, same ECR image as API
  - [ ] Command: `["python", "-m", "app.workers.sqs_consumer"]`
  - [ ] No port mapping (no HTTP listener)
  - [ ] CPU: 512, Memory: 1024 (prod) — override via variable
  - [ ] Same Secrets + environment var pattern as API task definition
  - [ ] Log driver: `awslogs`, log group `/truerag/worker`, region `us-east-1`, stream prefix `worker`
  - [ ] No ALB, no health check endpoint — health inferred from task running status

- [ ] Task 7: `truerag-worker` ECS service (AC: 3)
  - [ ] Service `truerag-worker` using Fargate launch type
  - [ ] Desired count: 1 (baseline) — scaled by Application Auto Scaling
  - [ ] No load balancer
  - [ ] Network mode: `awsvpc` in private subnets with outbound internet via NAT (SQS, S3, external APIs)

- [ ] Task 8: Application Auto Scaling for worker (AC: 3)
  - [ ] Register `truerag-worker` ECS service as scalable target (min 1, max 5)
  - [ ] Scaling policy: step scaling on SQS `ApproximateNumberOfMessagesVisible` metric
  - [ ] Scale out: add 1 task when queue depth > 10 for 1 minute
  - [ ] Scale in: remove 1 task when queue depth < 2 for 5 minutes (cooldown 300s)
  - [ ] CloudWatch alarm driving the scaling policy created here (separate from regression alarms in Story 10.3)

- [ ] Task 9: CloudWatch Log Groups (AC: 4)
  - [ ] Create `/truerag/api` log group, retention 30 days
  - [ ] Create `/truerag/worker` log group, retention 30 days
  - [ ] Log groups created as managed resources (not auto-created by ECS) so retention is enforced

- [ ] Task 10: Wire ECS module into environments (AC: 1)
  - [ ] Add ECS module call to `terraform/environments/prod/main.tf` and `dev/main.tf`
  - [ ] Pass networking outputs (subnets, security groups, ALB target group ARN) and secrets outputs (ARNs) as inputs

## Dev Notes

### Critical Architecture Constraints

- **Async separation is a topology constraint, not a convention** (D12): `truerag-api` and `truerag-worker` are completely separate ECS services with separate task definitions and separate IAM roles. They share the same Docker image but run different entry points. Never combine them into a single service.
- **No HTTP listener on worker**: `app/workers/sqs_consumer.py` is the entry point for the worker container. It has no FastAPI app, no port binding. The ECS task definition must NOT define any port mappings for the worker.
- **Gunicorn on ECS**: Architecture specifies Gunicorn as process manager on ECS Fargate (not bare Uvicorn). Command must be `gunicorn -k uvicorn.workers.UvicornWorker`.
- **Secrets injection via ECS secrets block**: All credentials from Secrets Manager must be injected as environment variables via the ECS task definition `secrets` block (not application-level `secrets.py` startup reads). The `app/utils/secrets.py` wrapper reads at operation time — this is for runtime credential rotation. The ECS secrets block handles initial injection at task start.
- **`/v1/ready` health check**: The readiness endpoint defined in `app/api/v1/observability.py` (FR55). ALB health check MUST use this endpoint. Liveness can use `/v1/health`. Do not use `/` or any other path.
- **DynamoDB table names**: IAM policy for task role must reference the exact table names `truerag-audit-log` and `truerag-ingestion-jobs` from Story 10.1.

### Scaling Architecture

| Service | Scales On | Metric |
|---|---|---|
| `truerag-api` | CPU utilisation or ALB request count | CloudWatch `CPUUtilization` or `RequestCountPerTarget` |
| `truerag-worker` | SQS queue depth | `ApproximateNumberOfMessagesVisible` on ingestion queue |

### Log Format

All application logs are structured JSON (D15). CloudWatch Logs Insights queries will use `@message` field. Do not configure any log filtering or transformation at the ECS level — raw stdout is sufficient.

Expected log entry shape (from `app/utils/observability.py`):
```json
{
  "timestamp": "ISO8601",
  "level": "INFO | WARNING | ERROR",
  "tenant_id": "string | null",
  "agent_id": "string | null",
  "request_id": "string",
  "operation": "string",
  "latency_ms": "integer | null",
  "extra": {}
}
```

### Security Groups

- `truerag-api` tasks: inbound only from ALB security group on port 8000; outbound to RDS, MongoDB Atlas CIDR, SQS/S3/DynamoDB VPC endpoints (or NAT)
- `truerag-worker` tasks: no inbound; outbound to S3, SQS, DynamoDB, pgvector, MongoDB Atlas CIDR, external embedding/LLM APIs

### File Structure

```
terraform/modules/ecs/
├── main.tf        # Cluster, task defs, services, auto scaling, log groups
├── variables.tf   # image_uri, cpu, memory, desired_count, sqs_queue_url, subnet_ids, etc.
└── outputs.tf     # cluster_name, api_service_name, worker_service_name, task_role_arn
```

### ADR Required

Create `docs/adrs/adr-017-ecs-fargate-topology.md` documenting: separate task definition decision, Gunicorn worker count rationale, auto scaling thresholds chosen.

### Project Structure Notes

- `terraform/modules/ecs/` directory stub may exist from Story 10.1 — add files into it
- Do NOT touch any `app/` code in this story
- `app/workers/sqs_consumer.py` entry point already implemented — match command exactly

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Infrastructure & Deployment] — D12 ECS topology table
- [Source: _bmad-output/planning-artifacts/architecture.md#Architectural Boundaries] — Worker boundary definition
- [Source: _bmad-output/planning-artifacts/architecture.md#D15] — Structured logging format
- [Source: _bmad-output/planning-artifacts/epics.md#Story 10.2 AC] — Exact service requirements
- [Source: _bmad-output/planning-artifacts/epics.md#NonFunctional Requirements] — NFR13, NFR14

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
