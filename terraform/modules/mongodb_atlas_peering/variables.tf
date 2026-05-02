variable "enable_atlas_peering" {
  type    = bool
  default = false
}

variable "atlas_project_id" {
  type    = string
  default = ""
}

variable "atlas_container_id" {
  type    = string
  default = ""
}

variable "atlas_cidr_block" {
  type    = string
  default = ""
}

variable "aws_account_id" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "private_route_table_ids" {
  type = list(string)
}
