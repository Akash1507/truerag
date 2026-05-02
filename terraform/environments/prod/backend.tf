terraform {
  backend "s3" {
    key     = "truerag/prod/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}
