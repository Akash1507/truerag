variable "name_prefix" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "rds_security_group_id" {
  type = string
}

variable "instance_class" {
  type = string
}

variable "allocated_storage" {
  type = number
}

variable "db_name" {
  type    = string
  default = "truerag"
}

variable "db_username" {
  type    = string
  default = "truerag"
}

variable "db_password_placeholder" {
  description = "Non-secret bootstrap value replaced out-of-band"
  type        = string
  default     = "REPLACE_OUT_OF_BAND"
}

variable "backup_retention_period" {
  type    = number
  default = 7
}

variable "skip_final_snapshot" {
  type    = bool
  default = false
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "multi_az" {
  type = bool
}

variable "tags" {
  type    = map(string)
  default = {}
}
