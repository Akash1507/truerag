# Story 10.3: CloudWatch Alarms & RAGAS Regression Alerting

Status: ready-for-dev

## Story

As a Platform Admin,
I want CloudWatch alarms provisioned for RAGAS regression detection and critical infrastructure metrics,
so that quality regressions and infrastructure failures trigger automatic notifications without manual monitoring (FR42, NFR13).

## Acceptance Criteria

1. **Given** `terraform/modules/cloudwatch/` **When** applied **Then** a CloudWatch alarm is configured on the custom RAGAS faithfulness metric (written by `eval_service.py`) that triggers when the metric falls below the configured threshold; the alarm is connected to an SNS topic with an email subscription.

2. **Given** the RAGAS regression alarm triggers **When** SNS delivers the notification **Then** the notification includes `tenant_id`, `agent_id`, the score that triggered the alert, and the threshold value; v1 delivers email only — Slack/webhook deferred to v2 as documented in ADR.

3. **Given** infrastructure alarms provisioned in Terraform **When** inspected **Then** alarms exist for: ECS service `truerag-api` unhealthy task count > 0; RDS CPU utilisation > 80%; SQS DLQ message count > 0 (indicating failed ingestion jobs).

## Tasks / Subtasks

- [ ] Task 1: Create `terraform/modules/cloudwatch/` module (AC: 1, 3)
  - [ ] `terraform/modules/cloudwatch/main.tf` — SNS topic, alarms
  - [ ] `terraform/modules/cloudwatch/variables.tf` — thresholds, email, metric namespace
  - [ ] `terraform/modules/cloudwatch/outputs.tf` — SNS topic ARN, alarm names

- [ ] Task 2: SNS topic + email subscription (AC: 1, 2)
  - [ ] Create SNS topic `truerag-alerts`
  - [ ] Email subscription using `var.alert_email` variable
  - [ ] Note: SNS email subscriptions require manual confirmation — document this in README

- [ ] Task 3: RAGAS regression CloudWatch alarm (AC: 1, 2)
  - [ ] Alarm on custom metric namespace `TrueRAG/Eval`, metric name `RAGASFaithfulness`
  - [ ] Dimensions: match what `eval_service.py` writes — `TenantId` and `AgentId`
  - [ ] Threshold: `var.ragas_faithfulness_threshold` (default 0.6 per NFR4: baseline > 0.7, alert < 0.6)
  - [ ] Comparison: `LessThanThreshold`
  - [ ] Evaluation periods: 1, period: 300s (5 min)
  - [ ] Treat missing data: `notBreaching` (no eval run = no alert)
  - [ ] Alarm action: SNS topic ARN
  - [ ] Alarm description must match AC2 requirement for tenant/agent context — this comes from metric dimensions, not alarm message body; document limitation in ADR

- [ ] Task 4: Cross-check `eval_service.py` metric write format (AC: 1, 2)
  - [ ] Read `app/services/eval_service.py` to confirm exact metric namespace, metric name, and dimension keys used in `put_metric_data` call
  - [ ] If `eval_service.py` not yet implemented (Story 6.1-6.4 may be in-progress), define the expected contract and leave a comment in the Terraform code specifying what `eval_service.py` must write
  - [ ] Alarm namespace/dimensions MUST exactly match what `eval_service.py` writes — mismatch = alarm never fires

- [ ] Task 5: ECS unhealthy task alarm (AC: 3)
  - [ ] Alarm: `AWS/ECS` namespace, metric `RunningTaskCount` on cluster `truerag`, service `truerag-api`
  - [ ] Alternative: use ALB `UnHealthyHostCount` metric from `AWS/ApplicationELB` namespace for more precise health signal
  - [ ] Threshold: `LessThanThreshold`, value `var.api_desired_count` (e.g., 2 in prod, 1 in dev)
  - [ ] Period: 60s, evaluation periods: 2
  - [ ] Alarm action: SNS topic ARN

- [ ] Task 6: RDS CPU alarm (AC: 3)
  - [ ] Alarm: `AWS/RDS` namespace, metric `CPUUtilization`
  - [ ] Threshold: 80%, `GreaterThanThreshold`
  - [ ] Period: 300s, evaluation periods: 2
  - [ ] Alarm action: SNS topic ARN

- [ ] Task 7: SQS DLQ depth alarm (AC: 3)
  - [ ] Alarm: `AWS/SQS` namespace, metric `ApproximateNumberOfMessagesVisible` on DLQ
  - [ ] Threshold: 0, `GreaterThanThreshold`
  - [ ] Period: 60s, evaluation periods: 1
  - [ ] Alarm action: SNS topic ARN
  - [ ] This alarm fires the moment any message lands in DLQ — failed ingestion requires investigation

- [ ] Task 8: Wire cloudwatch module into environments (AC: 1, 3)
  - [ ] Add cloudwatch module call to `terraform/environments/prod/main.tf`
  - [ ] Pass SQS DLQ ARN from sqs module, ECS service name from ecs module, RDS instance ID from rds module
  - [ ] Set `alert_email` variable — use `var.alert_email` in tfvars.example (no actual email hardcoded)

- [ ] Task 9: Write ADR for alerting approach (AC: 2)
  - [ ] Create `docs/adrs/adr-018-ragas-regression-alerting.md`
  - [ ] Document: v1 email-only via SNS; Slack/webhook deferred to v2; limitation that alarm message body does not contain score/threshold values (those are in CloudWatch metrics); rationale for `notBreaching` on missing data

## Dev Notes

### Critical Architecture Constraints

- **RAGAS metric write path** (FR42, architecture data boundary table): `app/services/eval_service.py` is the ONLY service that writes to CloudWatch. It uses `aioboto3` `put_metric_data`. The Terraform alarm MUST match the exact namespace/metric/dimensions used there.
  - Expected: namespace `TrueRAG/Eval`, metric name `RAGASFaithfulness`, dimensions `TenantId` + `AgentId`
  - If `eval_service.py` has not been implemented yet (Story 6 in-progress), define the contract in both the alarm and as a comment/assertion in `eval_service.py`

- **NFR4 thresholds**: baseline > 0.7, alert threshold < 0.6. The alarm threshold variable default MUST be 0.6.

- **v1 alert delivery = email only**: SNS → email subscription. The acceptance criteria explicitly defers Slack/webhook to v2. Do NOT add webhook or Lambda forwarding in this story.

- **Alarm message limitation**: CloudWatch alarm notifications contain alarm name, state, reason string, and metric data. The SNS message will NOT automatically include `tenant_id`/`agent_id` as human-readable text in the email body — they appear as metric dimensions in the JSON. This is a known v1 limitation. Document in ADR-018.

- **SNS email subscription requires manual confirmation**: After `terraform apply`, the ops team must click the confirmation link sent to `alert_email`. This is an AWS constraint — document in deployment runbook (README or ADR).

### Metric Contract (align with eval_service.py)

```python
# Expected call in app/services/eval_service.py:
await cloudwatch_client.put_metric_data(
    Namespace="TrueRAG/Eval",
    MetricData=[{
        "MetricName": "RAGASFaithfulness",
        "Dimensions": [
            {"Name": "TenantId", "Value": tenant_id},
            {"Name": "AgentId", "Value": agent_id},
        ],
        "Value": faithfulness_score,
        "Unit": "None",
    }]
)
```

Terraform alarm must use:
```hcl
namespace   = "TrueRAG/Eval"
metric_name = "RAGASFaithfulness"
dimensions  = { TenantId = "*", AgentId = "*" }  # or specific eval agent dimensions
```

### CloudWatch Alarm Summary

| Alarm | Namespace | Metric | Threshold | Action |
|---|---|---|---|---|
| RAGAS Faithfulness | `TrueRAG/Eval` | `RAGASFaithfulness` | < 0.6 | SNS email |
| API Unhealthy Tasks | `AWS/ApplicationELB` | `UnHealthyHostCount` | > 0 | SNS email |
| RDS CPU High | `AWS/RDS` | `CPUUtilization` | > 80% | SNS email |
| SQS DLQ Non-Empty | `AWS/SQS` | `ApproximateNumberOfMessagesVisible` | > 0 | SNS email |

### File Structure

```
terraform/modules/cloudwatch/
├── main.tf        # SNS topic, email subscription, all 4 alarms
├── variables.tf   # alert_email, ragas_faithfulness_threshold, alb_arn_suffix, etc.
└── outputs.tf     # sns_topic_arn, alarm_names
```

### Project Structure Notes

- `terraform/modules/cloudwatch/` stub created in Story 10.1 — add files
- `docs/adrs/` already has `README.md` — add ADR-018
- Read `app/services/eval_service.py` before writing the alarm to verify metric contract

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Data Boundary table] — CloudWatch accessed by `eval_service.py` via `aioboto3`
- [Source: _bmad-output/planning-artifacts/architecture.md#Regression alert path] — eval_service → CloudWatch → SNS email flow
- [Source: _bmad-output/planning-artifacts/epics.md#Story 10.3 AC] — exact alarm requirements
- [Source: _bmad-output/planning-artifacts/epics.md#NonFunctional Requirements] — NFR4 thresholds (baseline > 0.7, alert < 0.6)
- [Source: _bmad-output/planning-artifacts/architecture.md#Architecture Validation Results] — "v2: Slack/webhook push" deferred note

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
