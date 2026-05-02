variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_account_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "alb_certificate_arn" {
  type = string
}

variable "document_archive_bucket_name" {
  type = string
}

variable "rds_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "rds_allocated_storage" {
  type    = number
  default = 100
}

variable "enable_atlas_peering" {
  type    = bool
  default = true
}

variable "atlas_project_id" {
  type = string
}

variable "atlas_container_id" {
  type = string
}

variable "atlas_cidr_block" {
  type = string
}

variable "mongodb_atlas_public_key" {
  description = "Atlas API public key supplied via CI/CLI"
  type        = string
  default     = ""
}

variable "mongodb_atlas_private_key" {
  description = "Atlas API private key supplied via CI/CLI"
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
