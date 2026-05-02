terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "ecs" {
  source = "../../modules/ecs"

  aws_region              = var.aws_region
  environment             = "prod"
  name_prefix             = "truerag"
  vpc_id                  = var.vpc_id
  private_subnet_ids      = var.private_subnet_ids
  alb_security_group_id   = var.alb_security_group_id
  api_target_group_arn    = var.api_target_group_arn
  container_image_uri     = var.container_image_uri
  api_desired_count       = 2
  worker_desired_count    = 1
  api_cpu                 = 1024
  api_memory              = 2048
  worker_cpu              = 512
  worker_memory           = 1024
  api_environment_variables    = var.api_environment_variables
  worker_environment_variables = var.worker_environment_variables
  api_secret_arns              = var.api_secret_arns
  worker_secret_arns           = var.worker_secret_arns
  ingestion_queue_arn          = var.ingestion_queue_arn
  ingestion_queue_name         = var.ingestion_queue_name
  audit_log_table_arn          = var.audit_log_table_arn
  ingestion_jobs_table_arn     = var.ingestion_jobs_table_arn
  document_bucket_arn          = var.document_bucket_arn
  db_security_group_ids        = var.db_security_group_ids
}

module "cloudwatch" {
  source = "../../modules/cloudwatch"

  alert_email                  = var.alert_email
  ragas_metric_namespace       = var.ragas_metric_namespace
  ragas_metric_name            = var.ragas_metric_name
  ragas_faithfulness_threshold = var.ragas_faithfulness_threshold
  ecs_cluster_name             = module.ecs.cluster_name
  ecs_service_name             = module.ecs.api_service_name
  api_desired_count            = 2
  rds_instance_id              = var.rds_instance_id
  rds_cpu_threshold            = var.rds_cpu_threshold
  sqs_dlq_name                 = var.sqs_dlq_name
  ragas_alarm_tenant_id        = var.ragas_alarm_tenant_id
  ragas_alarm_agent_id         = var.ragas_alarm_agent_id
}

variable "aws_region" { type = string default = "us-east-1" }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "alb_security_group_id" { type = string }
variable "api_target_group_arn" { type = string }
variable "container_image_uri" { type = string }
variable "api_environment_variables" { type = map(string) default = {} }
variable "worker_environment_variables" { type = map(string) default = {} }
variable "api_secret_arns" { type = map(string) default = {} }
variable "worker_secret_arns" { type = map(string) default = {} }
variable "ingestion_queue_arn" { type = string }
variable "ingestion_queue_name" { type = string }
variable "audit_log_table_arn" { type = string }
variable "ingestion_jobs_table_arn" { type = string }
variable "document_bucket_arn" { type = string }
variable "db_security_group_ids" { type = list(string) default = [] }
variable "alert_email" { type = string default = "alerts@example.com" }
variable "ragas_metric_namespace" { type = string default = "TrueRAG/Eval" }
variable "ragas_metric_name" { type = string default = "RAGASFaithfulness" }
variable "ragas_faithfulness_threshold" { type = number default = 0.6 }
variable "rds_instance_id" { type = string default = "truerag-prod" }
variable "rds_cpu_threshold" { type = number default = 80 }
variable "sqs_dlq_name" { type = string default = "truerag-ingestion-dlq" }
variable "ragas_alarm_tenant_id" { type = string default = "all" }
variable "ragas_alarm_agent_id" { type = string default = "all" }
