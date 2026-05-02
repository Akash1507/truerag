terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_dynamodb_table" "audit_log" {
  name         = "truerag-audit-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "timestamp#query_hash"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "timestamp#query_hash"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, { Name = "truerag-audit-log" })
}

resource "aws_dynamodb_table" "ingestion_jobs" {
  name         = "truerag-ingestion-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, { Name = "truerag-ingestion-jobs" })
}
