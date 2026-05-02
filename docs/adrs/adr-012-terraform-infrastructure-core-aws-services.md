# ADR-012: Terraform Infrastructure for Core AWS Services

- Status: Accepted
- Date: 2026-05-03

## Context

Epic 10 requires production-grade AWS infrastructure provisioning for TrueRAG with no manual console-driven drift, shared environment modules, encryption at rest, and strict secret handling. Story 10.1 also requires an explicit strategy for MongoDB Atlas peering in `us-east-1`.

## Decision

1. Use a module-first Terraform layout under `terraform/modules/` and instantiate the same modules from `terraform/environments/dev/` and `terraform/environments/prod/`.
2. Provision required core resources in modules:
   - networking: VPC, public/private subnets, IGW, NAT, route tables, ALB, security groups, HTTPS listener and HTTP redirect.
   - rds: PostgreSQL 15, encrypted storage, private subnet group, parameter group for pg settings.
   - sqs: standard queue + DLQ with redrive policy.
   - s3: document archive bucket with versioning, SSE (AES256), public access block, HTTPS-only bucket policy.
   - dynamodb: exact table names `truerag-audit-log` and `truerag-ingestion-jobs`, PAY_PER_REQUEST, SSE enabled.
   - secrets: Secrets Manager placeholders using `jsonencode({})` and IAM read policy for ECS task roles.
   - ecr: `truerag` repository with scan-on-push and lifecycle retention of last 10 images.
3. Keep secret values out of Terraform-managed configuration. Secrets are provisioned as empty placeholders and populated out-of-band by operations.
4. Implement MongoDB Atlas peering through a dedicated optional module (`mongodb_atlas_peering`) using the Atlas provider when credentials are available. The module can be disabled for environments where Atlas setup is deferred.

## Consequences

- Pros:
  - Environment consistency and reduced drift through shared modules.
  - Compliance with no-secrets-in-code policy.
  - Security requirements encoded directly in IaC for encryption and HTTPS enforcement.
  - Atlas peering path is codified and repeatable when provider credentials exist.
- Cons:
  - Atlas peering depends on external Atlas API credentials and project/container identifiers.
  - `pgvector` extension creation remains a post-provision database step (`CREATE EXTENSION IF NOT EXISTS vector;`) and must be executed after DB initialization.

## Alternatives Considered

1. Duplicate environment logic per folder.
   - Rejected: violates module reuse requirement and increases drift risk.
2. Store runtime secrets as Terraform variables and pass from CI.
   - Rejected: increases chance of secret leakage into state.
3. Manual Atlas peering only.
   - Partially rejected: kept as fallback, but codified provider path is preferred for repeatability.
