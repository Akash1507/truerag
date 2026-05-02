terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  secret_names = [
    "mongodb-uri",
    "rds-password",
    "openai-api-key",
    "anthropic-api-key",
    "jwt-secret"
  ]
}

resource "aws_secretsmanager_secret" "this" {
  for_each = toset(local.secret_names)

  name        = "${var.name_prefix}/${each.value}"
  description = "Placeholder only. Value is populated out-of-band."

  tags = merge(var.tags, { Name = "${var.name_prefix}/${each.value}" })
}

resource "aws_secretsmanager_secret_version" "placeholder" {
  for_each = aws_secretsmanager_secret.this

  secret_id     = each.value.id
  secret_string = jsonencode({})
}

data "aws_iam_policy_document" "ecs_read_secrets" {
  statement {
    sid     = "ReadRuntimeSecrets"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      for s in aws_secretsmanager_secret.this : s.arn
    ]
  }
}

resource "aws_iam_policy" "ecs_read_secrets" {
  name        = "${var.name_prefix}-ecs-read-secrets"
  description = "Read access for ECS task roles to TrueRAG runtime secrets"
  policy      = data.aws_iam_policy_document.ecs_read_secrets.json

  tags = var.tags
}
