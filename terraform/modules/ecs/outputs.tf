output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "api_service_name" {
  description = "ECS API service name."
  value       = aws_ecs_service.api.name
}

output "worker_service_name" {
  description = "ECS worker service name."
  value       = aws_ecs_service.worker.name
}

output "task_role_arn" {
  description = "Backward-compatible API task role ARN output."
  value       = aws_iam_role.api_task.arn
}

output "api_task_role_arn" {
  description = "API task role ARN."
  value       = aws_iam_role.api_task.arn
}

output "worker_task_role_arn" {
  description = "Worker task role ARN."
  value       = aws_iam_role.worker_task.arn
}

output "task_execution_role_arn" {
  description = "ECS task execution role ARN."
  value       = aws_iam_role.task_execution.arn
}
