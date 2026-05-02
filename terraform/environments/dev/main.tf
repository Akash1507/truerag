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
  environment             = "dev"
  name_prefix             = "truerag"
  vpc_id                  = var.vpc_id
  private_subnet_ids      = var.private_subnet_ids
  alb_security_group_id   = var.alb_security_group_id
  api_target_group_arn    = var.api_target_group_arn
  container_image_uri     = var.container_image_uri
  api_desired_count       = 1
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
