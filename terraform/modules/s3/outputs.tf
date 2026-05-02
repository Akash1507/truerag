output "bucket_name" {
  value = aws_s3_bucket.archive.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.archive.arn
}
