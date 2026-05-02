output "secret_arns" {
  value = {
    for name, secret in aws_secretsmanager_secret.this : name => secret.arn
  }
}

output "ecs_read_secrets_policy_arn" {
  value = aws_iam_policy.ecs_read_secrets.arn
}
