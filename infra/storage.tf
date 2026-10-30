# The two data buckets: the data lake in the primary Region and the replica target in the second
# Region. Lab objects expire after a day; Terraform empties the buckets on destroy (force_destroy).

locals {
  # The account ID is only used where AWS requires it (log-delivery policy, flow-log path), never in names.
  account_id = data.aws_caller_identity.current.account_id
}

# ---- data lake (us-east-1) ----

resource "aws_s3_bucket" "lake" {
  bucket        = "${local.name}-lake-${var.name_suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    id     = "expire-lab-objects"
    status = "Enabled"
    filter {}
    expiration {
      days = 1
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# Refuse any request that isn't over TLS (the CLI on the instances always uses HTTPS).
resource "aws_s3_bucket_policy" "lake" {
  bucket = aws_s3_bucket.lake.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TLSOnly"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.lake.arn, "${aws_s3_bucket.lake.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.lake]
}

# ---- replica target (eu-west-1): same settings, created in the second Region ----

resource "aws_s3_bucket" "replica" {
  region        = var.second_region
  bucket        = "${local.name}-replica-${var.name_suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "replica" {
  region                  = var.second_region
  bucket                  = aws_s3_bucket.replica.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "replica" {
  region = var.second_region
  bucket = aws_s3_bucket.replica.id
  rule {
    id     = "expire-lab-objects"
    status = "Enabled"
    filter {}
    expiration {
      days = 1
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_policy" "replica" {
  region = var.second_region
  bucket = aws_s3_bucket.replica.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TLSOnly"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.replica.arn, "${aws_s3_bucket.replica.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.replica]
}
