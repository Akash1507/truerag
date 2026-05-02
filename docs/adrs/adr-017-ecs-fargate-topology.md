# ADR-017: ECS Fargate Topology for API/Worker Separation

## Status
Accepted

## Date
2026-05-03

## Context
Story 10.2 requires deployment topology that enforces asynchronous separation between retrieval and ingestion workloads, while keeping operations simple for v1.

## Decision
1. Deploy `truerag-api` and `truerag-worker` as separate ECS services and separate task definitions.
2. Use Gunicorn with Uvicorn workers for API process management on Fargate:
   - command: `gunicorn -k uvicorn.workers.UvicornWorker -w 2 app.main:app --bind 0.0.0.0:8000`
3. Apply worker autoscaling on SQS queue depth:
   - scale out: +1 when `ApproximateNumberOfMessagesVisible > 10` for 1 minute
   - scale in: -1 when `< 2` for 5 minutes with 300 second cooldown

## Rationale
- Separate ECS services provide hard operational isolation so ingestion surges do not consume API compute.
- Gunicorn provides resilient process supervision and predictable worker model for FastAPI under Fargate.
- Queue-depth scaling maps directly to worker backlog and keeps baseline cost low.

## Consequences
- Two task roles and service definitions increase Terraform surface area but improve least-privilege control.
- API and worker can evolve scaling policies independently without redeploying each other.
