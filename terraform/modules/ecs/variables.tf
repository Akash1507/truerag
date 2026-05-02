variable "aws_region" {
  description = "AWS region for ECS and CloudWatch resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g. dev, prod)."
  type        = string
}

variable "name_prefix" {
  description = "Prefix for named AWS resources."
  type        = string
  default     = "truerag"
}

variable "vpc_id" {
  description = "VPC ID where ECS services will run."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for Fargate tasks."
  type        = list(string)
}

variable "alb_security_group_id" {
  description = "Security group ID attached to ALB."
  type        = string
}

variable "api_target_group_arn" {
  description = "ALB target group ARN for truerag-api service."
  type        = string
}

variable "container_image_uri" {
  description = "ECR image URI for API and worker tasks."
  type        = string
}

variable "task_execution_role_name" {
  description = "IAM role name for ECS task execution role."
  type        = string
  default     = "truerag-task-execution-role"
}

variable "api_desired_count" {
  description = "Desired API service task count."
  type        = number
  default     = 2
}

variable "worker_desired_count" {
  description = "Desired worker baseline task count."
  type        = number
  default     = 1
}

variable "api_cpu" {
  description = "CPU units for API task definition."
  type        = number
  default     = 1024
}

variable "api_memory" {
  description = "Memory (MiB) for API task definition."
  type        = number
  default     = 2048
}

variable "worker_cpu" {
  description = "CPU units for worker task definition."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Memory (MiB) for worker task definition."
  type        = number
  default     = 1024
}

variable "api_environment_variables" {
  description = "Non-secret environment variables for API container."
  type        = map(string)
  default     = {}
}

variable "worker_environment_variables" {
  description = "Non-secret environment variables for worker container."
  type        = map(string)
  default     = {}
}

variable "api_secret_arns" {
  description = "Map of API env var name -> Secrets Manager ARN."
  type        = map(string)
  default     = {}
}

variable "worker_secret_arns" {
  description = "Map of worker env var name -> Secrets Manager ARN."
  type        = map(string)
  default     = {}
}

variable "ingestion_queue_arn" {
  description = "SQS ingestion queue ARN for IAM and autoscaling alarms."
  type        = string
}

variable "ingestion_queue_name" {
  description = "SQS ingestion queue name for CloudWatch alarms."
  type        = string
}

variable "audit_log_table_arn" {
  description = "DynamoDB audit log table ARN."
  type        = string
}

variable "ingestion_jobs_table_arn" {
  description = "DynamoDB ingestion jobs table ARN."
  type        = string
}

variable "document_bucket_arn" {
  description = "S3 bucket ARN used by ingestion and retrieval flows."
  type        = string
}

variable "db_security_group_ids" {
  description = "Security group IDs reachable from ECS tasks (RDS/proxy/etc)."
  type        = list(string)
  default     = []
}

variable "worker_min_capacity" {
  description = "Minimum worker task count for Application Auto Scaling."
  type        = number
  default     = 1
}

variable "worker_max_capacity" {
  description = "Maximum worker task count for Application Auto Scaling."
  type        = number
  default     = 5
}

variable "worker_scale_out_queue_depth" {
  description = "Scale-out threshold for ApproximateNumberOfMessagesVisible."
  type        = number
  default     = 10
}

variable "worker_scale_in_queue_depth" {
  description = "Scale-in threshold for ApproximateNumberOfMessagesVisible."
  type        = number
  default     = 2
}

variable "api_cpu_target" {
  description = "Target average ECS CPU utilization for API autoscaling."
  type        = number
  default     = 60
}
