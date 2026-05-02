variable "name_prefix" {
  description = "Name prefix for resources"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "alb_certificate_arn" {
  description = "ACM certificate ARN for ALB HTTPS listener"
  type        = string
}

variable "api_container_port" {
  description = "Port exposed by API tasks"
  type        = number
  default     = 8000
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}
