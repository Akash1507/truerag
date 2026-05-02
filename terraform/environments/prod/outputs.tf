output "vpc_id" {
  value = module.networking.vpc_id
}

output "db_endpoint" {
  value = module.rds.db_endpoint
}

output "sqs_queue_arn" {
  value = module.sqs.queue_arn
}

output "s3_bucket_name" {
  value = module.s3.bucket_name
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}
