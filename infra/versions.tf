terraform {
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.60"
    }
  }

  # Remote state in the shared bucket (one key per project), passed at init time:
  #   terraform init -backend-config="bucket=nkosi-tfstate-<account id>"
  backend "s3" {
    key          = "aws-data-transfer-cost-forensics/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

# One provider for both Regions: AWS provider 6.x takes a per-resource "region" argument, so the
# eu-west-1 replica bucket sets region = var.second_region instead of needing a provider alias.
provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "aws-data-transfer-cost-forensics"
      ManagedBy = "terraform"
    }
  }
}
