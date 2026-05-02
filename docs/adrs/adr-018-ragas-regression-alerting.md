# ADR-018: RAGAS Regression Alerting via CloudWatch + SNS (Email v1)

## Status
Accepted

## Context
Story 10.3 requires automated alerting for RAGAS faithfulness regressions and core infrastructure health signals. The evaluation service emits custom CloudWatch metrics, and the operations path must notify without manual dashboard checks.

## Decision
- Provision `terraform/modules/cloudwatch/` with one SNS topic (`truerag-alerts`) and email subscription.
- Create alarms for:
  - RAGAS faithfulness regression (`TrueRAG/Eval` / `RAGASFaithfulness`, threshold `< 0.6`)
  - ECS API running task count below desired count
  - RDS CPU utilization above 80%
  - SQS DLQ visible message count above 0
- Use `treat_missing_data = "notBreaching"` for the RAGAS alarm so missing eval runs do not trigger false alerts.
- Keep delivery at v1 scope: SNS email only.

## Consequences
- Slack/webhook forwarding is deferred to v2 by design.
- CloudWatch/SNS alarm notifications do not provide a fully customized body containing tenant, agent, score, and threshold as free text.
  - Tenant and agent context is carried via CloudWatch metric dimensions (`TenantId`, `AgentId`).
  - Threshold is encoded in alarm configuration.
  - Triggering score is visible in CloudWatch alarm state/reason details.
- SNS email delivery requires manual subscription confirmation after apply.
