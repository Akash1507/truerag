output "sns_topic_arn" {
  description = "ARN for the shared alert SNS topic."
  value       = aws_sns_topic.alerts.arn
}

output "alarm_names" {
  description = "Created CloudWatch alarm names."
  value = {
    ragas_faithfulness = aws_cloudwatch_metric_alarm.ragas_faithfulness.alarm_name
    ecs_unhealthy      = aws_cloudwatch_metric_alarm.ecs_unhealthy_tasks.alarm_name
    rds_cpu_high       = aws_cloudwatch_metric_alarm.rds_cpu_high.alarm_name
    sqs_dlq_depth      = aws_cloudwatch_metric_alarm.sqs_dlq_depth.alarm_name
  }
}
