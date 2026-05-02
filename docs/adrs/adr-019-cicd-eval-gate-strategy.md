# ADR-019: CI-CD Pipeline with Production Eval Gate

## Status
Accepted

## Context
V1 has no separate staging environment. We still need a blocking CI-CD quality gate that validates retrieval quality before deployment can be considered successful.

## Decision
Use GitHub Actions with two workflows:
- `ci.yml` on pull requests for Ruff, mypy strict, and pytest (unit + integration).
- `deploy.yml` on pushes to `main` for Docker build/push to ECR and ECS rolling deployment, followed by a blocking RAGAS eval gate.

The eval gate calls the production deployment against a dedicated eval-only agent (`EVAL_AGENT_ID`) that has a stable golden dataset and fixed indexed documents.

## Required GitHub Actions Secrets
- `AWS_ROLE_ARN`: IAM role assumed by GitHub OIDC.
- `ECR_REGISTRY`: ECR registry URL, for example `123456789012.dkr.ecr.us-east-1.amazonaws.com`.
- `TRUERAG_API_URL`: Production API base URL.
- `TRUERAG_API_KEY`: API key scoped to the eval tenant.
- `EVAL_AGENT_ID`: Dedicated eval agent ID in production.
- `RAGAS_FAITHFULNESS_THRESHOLD`: Blocking threshold, default `0.6`.

## Eval Agent Provisioning
Provision once and treat it as CI infrastructure:
1. Create a dedicated tenant for eval automation.
2. Create one agent intended only for eval runs.
3. Seed the eval dataset via `POST /v1/agents/{agent_id}/eval` with golden Q/A pairs.
4. Index stable, versioned source documents for this agent.
5. Store the agent ID as `EVAL_AGENT_ID` and API key as `TRUERAG_API_KEY` in GitHub secrets.

## Async Eval Handling
`POST /v1/agents/{eval_agent_id}/eval/run` may return `202` with `run_id` when question count is high. The pipeline must poll `GET /v1/agents/{eval_agent_id}/eval/history` until the matching `run_id` appears or timeout is exceeded (default 10 minutes).

## Rollback Strategy
Current strategy is fail-fast with manual rollback/redeploy:
- If eval gate fails, the workflow exits non-zero and deployment is marked failed.
- ECS rolling settings with minimum healthy capacity preserve old tasks during rollout.
- Operators can rerun deployment after fix, or manually roll back service task definitions.

Automated rollback can be added later by capturing and restoring prior task definition revisions.
