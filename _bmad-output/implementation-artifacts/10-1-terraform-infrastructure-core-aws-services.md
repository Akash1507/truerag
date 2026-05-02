# Story 10.1: Terraform Infrastructure — Core AWS Services

Status: ready-for-dev

## Story

As an AI Platform Engineer,
I want all core AWS infrastructure provisioned via Terraform,
so that TrueRAG is deployable to production AWS with zero manual console steps (NFR13, NFR17–19).

## Acceptance Criteria

1. **Given** `terraform apply` in `terraform/environments/prod/` **When** it completes **Then** the following resources exist: VPC with public/private subnets; RDS PostgreSQL with pgvector extension enabled; SQS standard queue + DLQ (visibility timeout 300s, max receive count 3, DLQ retention 14 days); S3 document archive bucket; DynamoDB `truerag-audit-log` table (partition: `tenant_id`, sort: `timestamp#query_hash`); DynamoDB `truerag-ingestion-jobs` table (partition: `job_id`); AWS Secrets Manager entries (empty — values populated out-of-band); MongoDB Atlas VPC peering connection to `us-east-1`; ECR repository `truerag` with image scanning enabled and lifecycle policy retaining last 10 images.

2. **Given** the Terraform configuration **When** inspected **Then** no secret values (API keys, passwords, connection strings) appear anywhere in `.tf` files, `tfvars`, or Terraform state; all secret values are populated in Secrets Manager out-of-band.

3. **Given** `terraform/environments/dev/` and `terraform/environments/prod/` **When** compared **Then** they share modules from `terraform/modules/` with environment-specific variable overrides; no infrastructure logic is duplicated between environments.

4. **Given** Terraform configuration for data-at-rest encryption (NFR6) **When** `terraform plan` is run **Then** RDS has `storage_encrypted = true`; S3 has `server_side_encryption_configuration` set to `AES256` or `aws:kms`; DynamoDB tables have `server_side_encryption` enabled; all three enforced in `terraform/modules/` definitions.

5. **Given** ALB and API traffic (NFR5) **When** ALB listener configured **Then** HTTPS listener on port 443 is the only listener forwarding to `truerag-api` target group; HTTP port 80 redirects to HTTPS; TLS policy enforces minimum TLS 1.2.

## Tasks / Subtasks

- [ ] Task 1: Scaffold Terraform module structure (AC: 3)
  - [ ] Create `terraform/main.tf`, `variables.tf`, `outputs.tf` at root
  - [ ] Create `terraform/modules/networking/` — VPC, public/private subnets, security groups, ALB
  - [ ] Create `terraform/modules/rds/` — PostgreSQL + pgvector extension
  - [ ] Create `terraform/modules/sqs/` — ingestion queue + DLQ
  - [ ] Create `terraform/modules/s3/` — document archive bucket
  - [ ] Create `terraform/modules/dynamodb/` — audit-log + ingestion-jobs tables
  - [ ] Create `terraform/modules/secrets/` — Secrets Manager entries (no values)
  - [ ] Create `terraform/modules/ecr/` — ECR repository with scan + lifecycle policy
  - [ ] Create `terraform/environments/dev/` and `terraform/environments/prod/` calling shared modules

- [ ] Task 2: Networking module (AC: 1, 5)
  - [ ] VPC with CIDR block, public subnets (ALB), private subnets (ECS tasks, RDS)
  - [ ] Internet Gateway + NAT Gateway for private subnet outbound
  - [ ] Security groups: ALB (443 inbound public), ECS API (from ALB only), ECS worker (outbound only), RDS (from ECS tasks only)
  - [ ] ALB: HTTPS 443 listener → `truerag-api` target group; HTTP 80 listener → HTTPS redirect
  - [ ] ALB SSL policy enforcing minimum TLS 1.2 (`ELBSecurityPolicy-TLS13-1-2-2021-06` or equivalent)

- [ ] Task 3: RDS module (AC: 1, 4)
  - [ ] PostgreSQL 15+ instance with `storage_encrypted = true`
  - [ ] Parameter group enabling `pgvector` extension (`shared_preload_libraries`)
  - [ ] Multi-AZ: disabled in dev, enabled in prod via variable override
  - [ ] Subnet group in private subnets
  - [ ] Output connection endpoint (host + port); credentials stored in Secrets Manager via secrets module

- [ ] Task 4: SQS module (AC: 1)
  - [ ] Standard queue with visibility timeout 300s, message retention 4 days
  - [ ] DLQ with max receive count 3, retention 14 days
  - [ ] Redrive policy linking queue to DLQ

- [ ] Task 5: S3 module (AC: 1, 4)
  - [ ] Bucket with `server_side_encryption_configuration` (AES256 or aws:kms)
  - [ ] Block public access settings enabled
  - [ ] Versioning enabled for document archive integrity

- [ ] Task 6: DynamoDB module (AC: 1, 4)
  - [ ] `truerag-audit-log` table: partition key `tenant_id` (S), sort key `timestamp#query_hash` (S)
  - [ ] `truerag-ingestion-jobs` table: partition key `job_id` (S)
  - [ ] `server_side_encryption` enabled on both tables
  - [ ] Billing mode: PAY_PER_REQUEST

- [ ] Task 7: Secrets Manager module (AC: 2)
  - [ ] Create SecretString placeholders (empty `{}`) for: MongoDB URI, RDS password, OpenAI API key, Anthropic API key, JWT secret
  - [ ] No default values in `.tf` or `tfvars` — descriptions only
  - [ ] IAM policy allowing ECS task roles to read these secrets (referenced by ECS module in Story 10.2)

- [ ] Task 8: ECR module (AC: 1)
  - [ ] Repository `truerag` with `image_scanning_configuration { scan_on_push = true }`
  - [ ] Lifecycle policy: retain last 10 images (`imageCountMoreThan = 10`)

- [ ] Task 9: MongoDB Atlas VPC peering (AC: 1)
  - [ ] VPC peering connection resource to MongoDB Atlas us-east-1 (use `mongodbatlas_network_peering` if Atlas provider available, else document manual step in ADR)
  - [ ] Route table entries for Atlas CIDR in private subnets

- [ ] Task 10: Environment configs (AC: 3)
  - [ ] `terraform/environments/prod/main.tf` instantiating all modules with prod vars
  - [ ] `terraform/environments/dev/main.tf` instantiating all modules with dev vars (smaller RDS, no multi-AZ)
  - [ ] `terraform/environments/prod/terraform.tfvars.example` — no secrets, only structural values
  - [ ] `terraform/environments/dev/terraform.tfvars.example` — same

- [ ] Task 11: Validate `terraform validate` and `terraform fmt` pass in CI (AC: 4)

## Dev Notes

### Critical Architecture Constraints

- **No secrets anywhere in Terraform**: Secrets Manager entries are created as empty placeholders only. Credentials are set out-of-band by ops team. This is a hard requirement (NFR12). Do NOT set `secret_string` to real values. Use `secret_string = jsonencode({})` as placeholder.
- **Module reuse**: Both dev and prod environments MUST call shared modules in `terraform/modules/` — duplicating infra logic between environments is an architectural violation.
- **Region**: us-east-1 only (v1). Hardcode or set as variable default.
- **RDS pgvector**: The PostgreSQL instance needs `pgvector` extension. Provision via RDS parameter group with `shared_preload_libraries = 'pg_stat_statements'` and run `CREATE EXTENSION IF NOT EXISTS vector;` as a post-apply step (via `aws_db_instance` with a provisioner, or document as a manual post-step in README).
- **DynamoDB table names**: Must be exactly `truerag-audit-log` and `truerag-ingestion-jobs` — these are hardcoded in `app/services/eval_service.py`, `app/services/query_service.py`, and `app/services/ingestion_service.py`. Wrong names = runtime failures.
- **SQS config**: visibility timeout 300s matches `app/workers/sqs_consumer.py` poll config. Do not change.
- **ALB HTTPS enforcement**: HTTP → HTTPS redirect is a security requirement (NFR5). No plain HTTP traffic to API.

### File Structure

```
terraform/
├── main.tf                    # Root module — calls environment-specific setup
├── variables.tf               # Shared variable declarations
├── outputs.tf                 # Shared outputs
├── modules/
│   ├── networking/
│   │   ├── main.tf            # VPC, subnets, ALB, security groups
│   │   ├── variables.tf
│   │   └── outputs.tf         # vpc_id, private_subnet_ids, alb_target_group_arn
│   ├── rds/
│   │   ├── main.tf            # PostgreSQL + pgvector parameter group
│   │   ├── variables.tf
│   │   └── outputs.tf         # db_endpoint, db_port
│   ├── sqs/
│   │   ├── main.tf            # Queue + DLQ + redrive policy
│   │   ├── variables.tf
│   │   └── outputs.tf         # queue_url, queue_arn, dlq_url
│   ├── s3/
│   │   ├── main.tf            # Archive bucket + encryption + versioning
│   │   ├── variables.tf
│   │   └── outputs.tf         # bucket_name, bucket_arn
│   ├── dynamodb/
│   │   ├── main.tf            # audit-log + ingestion-jobs tables
│   │   ├── variables.tf
│   │   └── outputs.tf         # audit_log_table_name, ingestion_jobs_table_name
│   ├── cloudwatch/            # Created in Story 10.3 — leave empty module stub here
│   ├── secrets/
│   │   ├── main.tf            # Secrets Manager placeholder entries + IAM policy
│   │   ├── variables.tf
│   │   └── outputs.tf         # secret_arns map
│   ├── ecr/
│   │   ├── main.tf            # ECR repo + scan config + lifecycle policy
│   │   ├── variables.tf
│   │   └── outputs.tf         # repository_url
│   └── ecs/                   # Created in Story 10.2 — leave empty module stub here
└── environments/
    ├── dev/
    │   ├── main.tf            # Calls all modules with dev vars
    │   ├── variables.tf
    │   ├── terraform.tfvars.example
    │   └── backend.tf         # S3 remote state backend config
    └── prod/
        ├── main.tf            # Calls all modules with prod vars
        ├── variables.tf
        ├── terraform.tfvars.example
        └── backend.tf         # S3 remote state backend config
```

### Terraform Version & Provider Pins

- Terraform >= 1.5.0
- `hashicorp/aws` provider ~> 5.0
- `hashicorp/random` for any generated suffixes
- Pin versions in `terraform/modules/*/` with `required_providers` block

### Security Patterns

- ECS task role (defined in Story 10.2) needs IAM permissions to read specific Secrets Manager ARNs — reference the ARNs from the secrets module outputs
- S3 bucket policy: deny any `s3:GetObject` without HTTPS (`aws:SecureTransport = false` deny condition)
- RDS: no public accessibility (`publicly_accessible = false`)

### Encryption Requirements (NFR6)

| Resource | Encryption Config |
|---|---|
| RDS | `storage_encrypted = true`, `kms_key_id` optional (uses default aws/rds key) |
| S3 | `server_side_encryption_configuration` block with AES256 rule |
| DynamoDB | `server_side_encryption { enabled = true }` |

### ADR Required

Create `docs/adrs/adr-016-terraform-infrastructure-approach.md` documenting: module structure decision, secrets-out-of-band approach, MongoDB Atlas peering strategy (managed provider vs manual).

### Project Structure Notes

- `terraform/` directory exists with only `.gitkeep` — full scaffold needed
- `docs/adrs/` directory exists with `README.md` — add ADR-016 here
- Do NOT touch any `app/` code in this story

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Infrastructure & Deployment] — D12 ECS topology, D13 MongoDB hosting
- [Source: _bmad-output/planning-artifacts/epics.md#Story 10.1 AC] — exact resource list and encryption requirements
- [Source: _bmad-output/planning-artifacts/epics.md#NonFunctional Requirements] — NFR5, NFR6, NFR12, NFR13, NFR17-19
- [Source: _bmad-output/planning-artifacts/architecture.md#Project Structure] — `terraform/modules/` directory layout

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
