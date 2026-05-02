output "audit_log_table_name" {
  value = aws_dynamodb_table.audit_log.name
}

output "ingestion_jobs_table_name" {
  value = aws_dynamodb_table.ingestion_jobs.name
}
