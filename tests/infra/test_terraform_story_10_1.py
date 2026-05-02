import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class TestTerraformStory101(unittest.TestCase):
    def test_dynamodb_table_names_are_exact(self):
        content = read("terraform/modules/dynamodb/main.tf")
        self.assertIn('name         = "truerag-audit-log"', content)
        self.assertIn('name         = "truerag-ingestion-jobs"', content)

    def test_sqs_visibility_and_dlq_policy_are_set(self):
        content = read("terraform/modules/sqs/main.tf")
        self.assertIn("visibility_timeout_seconds = 300", content)
        self.assertIn("maxReceiveCount     = 3", content)
        self.assertIn("message_retention_seconds = 1209600", content)

    def test_encryption_requirements_present_in_modules(self):
        rds = read("terraform/modules/rds/main.tf")
        s3 = read("terraform/modules/s3/main.tf")
        dynamodb = read("terraform/modules/dynamodb/main.tf")
        self.assertIn("storage_encrypted   = true", rds)
        self.assertIn("aws_s3_bucket_server_side_encryption_configuration", s3)
        self.assertIn('sse_algorithm = "AES256"', s3)
        self.assertIn("server_side_encryption", dynamodb)

    def test_alb_https_only_forwarding_and_http_redirect(self):
        networking = read("terraform/modules/networking/main.tf")
        self.assertIn('port              = 443', networking)
        self.assertIn('protocol          = "HTTPS"', networking)
        self.assertIn('ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"', networking)
        self.assertIn('port              = 80', networking)
        self.assertIn('type = "redirect"', networking)

    def test_no_obvious_secret_literals_in_tfvars_examples(self):
        files = [
            "terraform/environments/dev/terraform.tfvars.example",
            "terraform/environments/prod/terraform.tfvars.example",
        ]
        forbidden = ["sk-", "AKIA", "BEGIN RSA", "mongodb+srv://", "password="]
        for file in files:
            content = read(file)
            for needle in forbidden:
                self.assertNotIn(needle, content)


if __name__ == "__main__":
    unittest.main()
