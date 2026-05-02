# ADR-011: Regression Detection via CloudWatch Metric + SNS Alert

**Status:** Accepted  
**Date:** 2026-05-03

## Context
Epic 6 introduces automated RAG quality checks using RAGAS. Platform admins need immediate signals when an agent regresses on faithfulness, without requiring manual dashboard monitoring.

In v1, Terraform-managed infrastructure already supports CloudWatch alarms and SNS email subscriptions. The application service needs to emit a reliable signal that infra can consume.

## Decision
TrueRAG v1 regression detection writes a CloudWatch custom metric from `eval_service.py` whenever a run's faithfulness is below the agent's configured threshold.

Metric contract:
- Namespace: `TrueRAG/EvalQuality`
- MetricName: `FaithfulnessRegression`
- Dimensions: `tenant_id`, `agent_id`
- Unit: `None`
- Value: faithfulness score for the regressing run

Alert delivery in v1 is CloudWatch Alarm -> SNS -> email, configured by Terraform. The application does not send direct Slack/webhook notifications in v1.

## Consequences
- Clear separation of concerns: application emits quality signal, infrastructure handles alert fanout.
- Non-fatal metric writes: experiment persistence is not blocked if CloudWatch write fails.
- Supports tenant/agent scoped alarms via dimensions.
- Slack/webhook push notifications are deferred to v2 to avoid coupling alert-channel logic into application runtime.
