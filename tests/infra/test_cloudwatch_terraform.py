from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_cloudwatch_module_has_required_resources_and_contract() -> None:
    main_tf = _read("terraform/modules/cloudwatch/main.tf")

    assert 'resource "aws_sns_topic" "alerts"' in main_tf
    assert 'name = "truerag-alerts"' in main_tf
    assert 'resource "aws_sns_topic_subscription" "email"' in main_tf
    assert 'protocol  = "email"' in main_tf
    assert 'endpoint  = var.alert_email' in main_tf

    assert 'resource "aws_cloudwatch_metric_alarm" "ragas_faithfulness"' in main_tf
    assert 'namespace           = var.ragas_metric_namespace' in main_tf
    assert 'metric_name         = var.ragas_metric_name' in main_tf
    assert 'comparison_operator = "LessThanThreshold"' in main_tf
    assert 'threshold           = var.ragas_faithfulness_threshold' in main_tf
    assert 'treat_missing_data  = "notBreaching"' in main_tf
    assert "TenantId" in main_tf
    assert "AgentId" in main_tf

    assert 'resource "aws_cloudwatch_metric_alarm" "ecs_unhealthy_tasks"' in main_tf
    assert 'namespace           = "AWS/ECS"' in main_tf
    assert 'metric_name         = "RunningTaskCount"' in main_tf
    assert 'comparison_operator = "LessThanThreshold"' in main_tf
    assert 'threshold           = var.api_desired_count' in main_tf

    assert 'resource "aws_cloudwatch_metric_alarm" "rds_cpu_high"' in main_tf
    assert 'namespace           = "AWS/RDS"' in main_tf
    assert 'metric_name         = "CPUUtilization"' in main_tf
    assert 'threshold           = var.rds_cpu_threshold' in main_tf
    assert 'comparison_operator = "GreaterThanThreshold"' in main_tf

    assert 'resource "aws_cloudwatch_metric_alarm" "sqs_dlq_depth"' in main_tf
    assert 'namespace           = "AWS/SQS"' in main_tf
    assert 'metric_name         = "ApproximateNumberOfMessagesVisible"' in main_tf
    assert 'comparison_operator = "GreaterThanThreshold"' in main_tf
    assert 'threshold           = 0' in main_tf


def test_cloudwatch_module_variables_and_outputs_exist() -> None:
    variables_tf = _read("terraform/modules/cloudwatch/variables.tf")
    outputs_tf = _read("terraform/modules/cloudwatch/outputs.tf")
    env_main_tf = _read("terraform/environments/prod/main.tf")

    assert 'variable "alert_email"' in variables_tf
    assert 'variable "ragas_faithfulness_threshold"' in variables_tf
    assert "default     = 0.6" in variables_tf
    assert 'variable "ragas_metric_namespace"' in variables_tf
    assert 'default     = "TrueRAG/Eval"' in variables_tf
    assert 'variable "ragas_metric_name"' in variables_tf
    assert 'default     = "RAGASFaithfulness"' in variables_tf

    assert 'output "sns_topic_arn"' in outputs_tf
    assert 'output "alarm_names"' in outputs_tf

    assert 'module "cloudwatch"' in env_main_tf
    assert 'source = "../../modules/cloudwatch"' in env_main_tf
