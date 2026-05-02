variable "alert_email" {
  description = "Email address for SNS alert subscription (manual confirmation required)."
  type        = string
}

variable "ragas_metric_namespace" {
  description = "Namespace used by eval_service CloudWatch metric writes."
  type        = string
  default     = "TrueRAG/Eval"
}

variable "ragas_metric_name" {
  description = "CloudWatch metric name written by eval_service for RAGAS faithfulness."
  type        = string
  default     = "RAGASFaithfulness"
}

variable "ragas_faithfulness_threshold" {
  description = "Faithfulness score threshold that triggers regression alarm."
  type        = number
  default     = 0.6
}

variable "ecs_cluster_name" {
  description = "ECS cluster name hosting truerag-api."
  type        = string
  default     = "truerag"
}

variable "ecs_service_name" {
  description = "ECS service name for API workload."
  type        = string
  default     = "truerag-api"
}

variable "api_desired_count" {
  description = "Minimum healthy running task count for API service."
  type        = number
  default     = 1
}

variable "rds_instance_id" {
  description = "RDS DB instance identifier for CPU monitoring."
  type        = string
}

variable "rds_cpu_threshold" {
  description = "RDS CPU utilization percentage threshold."
  type        = number
  default     = 80
}

variable "sqs_dlq_name" {
  description = "SQS DLQ queue name for failed ingestion jobs."
  type        = string
}

variable "ragas_alarm_tenant_id" {
  description = "TenantId dimension filter for the RAGAS alarm."
  type        = string
  default     = "all"
}

variable "ragas_alarm_agent_id" {
  description = "AgentId dimension filter for the RAGAS alarm."
  type        = string
  default     = "all"
}
