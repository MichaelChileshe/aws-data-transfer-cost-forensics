# The forensics side: VPC Flow Logs (custom v5 fields, Parquet, Hive-compatible hourly partitions,
# 60 s aggregation) into S3, a Glue table with partition projection over them, and an Athena
# workgroup with a bytes-scanned guard rail and its own expiring results bucket.

locals {
  # The custom record format, in this order. Parquet column names are the same with "-" -> "_".
  flow_fields = [
    "version", "account-id", "interface-id", "srcaddr", "dstaddr", "srcport", "dstport", "protocol",
    "packets", "bytes", "start", "end", "action", "log-status", "vpc-id", "subnet-id", "instance-id",
    "az-id", "sublocation-type", "flow-direction", "traffic-path", "pkt-src-aws-service",
    "pkt-dst-aws-service", "pkt-srcaddr", "pkt-dstaddr",
  ]
  # Parquet data types per the VPC Flow Logs field table (INT_32 -> int, INT_64 -> bigint).
  flow_int    = ["version", "srcport", "dstport", "protocol", "traffic-path"]
  flow_bigint = ["packets", "bytes", "start", "end"]

  flow_prefix = "s3://${aws_s3_bucket.flowlogs.bucket}/AWSLogs/aws-account-id=${local.account_id}/aws-service=vpcflowlogs/aws-region=${var.region}"
}

# ---- the flow-log bucket ----

resource "aws_s3_bucket" "flowlogs" {
  bucket        = "${local.name}-flowlogs-${var.name_suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "flowlogs" {
  bucket                  = aws_s3_bucket.flowlogs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "flowlogs" {
  bucket = aws_s3_bucket.flowlogs.id
  rule {
    id     = "expire-flow-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
  }
}

# The policy the VPC Flow Logs documentation gives for log delivery (service principal, confused-
# deputy conditions), with the Hive-compatible path. The flow-log service can rewrite a bucket's
# policy when it sets up delivery, so Terraform ignores later changes to it instead of fighting.
resource "aws_s3_bucket_policy" "flowlogs" {
  bucket = aws_s3_bucket.flowlogs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSLogDeliveryWrite"
        Effect    = "Allow"
        Principal = { Service = "delivery.logs.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.flowlogs.arn}/AWSLogs/aws-account-id=${local.account_id}/*"
        Condition = {
          StringEquals = { "aws:SourceAccount" = local.account_id, "s3:x-amz-acl" = "bucket-owner-full-control" }
          ArnLike      = { "aws:SourceArn" = "arn:aws:logs:${var.region}:${local.account_id}:*" }
        }
      },
      {
        Sid       = "AWSLogDeliveryAclCheck"
        Effect    = "Allow"
        Principal = { Service = "delivery.logs.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.flowlogs.arn
        Condition = {
          StringEquals = { "aws:SourceAccount" = local.account_id }
          ArnLike      = { "aws:SourceArn" = "arn:aws:logs:${var.region}:${local.account_id}:*" }
        }
      }
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.flowlogs]

  lifecycle {
    ignore_changes = [policy]
  }
}

# ---- the flow log: every ENI in the VPC (the instances AND the NAT gateway's ENI) ----

resource "aws_flow_log" "vpc" {
  vpc_id                   = aws_vpc.this.id
  traffic_type             = "ALL"
  log_destination_type     = "s3"
  log_destination          = aws_s3_bucket.flowlogs.arn
  max_aggregation_interval = 60
  log_format               = join(" ", [for f in local.flow_fields : format("$${%s}", f)])

  destination_options {
    file_format                = "parquet"
    hive_compatible_partitions = true
    per_hour_partition         = true
  }

  tags = { Name = "${local.name}-flowlog" }

  depends_on = [aws_s3_bucket_policy.flowlogs]
}

# ---- Glue table with partition projection: no crawler, no MSCK REPAIR; Athena computes the
# partition paths from year/month/day/hour and the template below ----

resource "aws_glue_catalog_database" "this" {
  name        = "mvela_xfer"
  description = "Mvelaphanda data-transfer forensics"
}

resource "aws_glue_catalog_table" "flows" {
  name          = "vpc_flow_logs"
  database_name = aws_glue_catalog_database.this.name
  table_type    = "EXTERNAL_TABLE"
  description   = "VPC flow logs, custom v5 format, Parquet, Hive-compatible hourly partitions"

  parameters = {
    "EXTERNAL"                  = "TRUE"
    "classification"            = "parquet"
    "projection.enabled"        = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2025,2035"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "projection.hour.type"      = "integer"
    "projection.hour.range"     = "0,23"
    "projection.hour.digits"    = "2"
    "storage.location.template" = "${local.flow_prefix}/year=$${year}/month=$${month}/day=$${day}/hour=$${hour}/"
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }

  storage_descriptor {
    location      = "${local.flow_prefix}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.flow_fields
      content {
        name = replace(columns.value, "-", "_")
        type = contains(local.flow_int, columns.value) ? "int" : (contains(local.flow_bigint, columns.value) ? "bigint" : "string")
      }
    }
  }
}

# ---- Athena: results bucket (expires) and a workgroup that enforces it plus a scan limit ----

resource "aws_s3_bucket" "athena" {
  bucket        = "${local.name}-athena-${var.name_suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "athena" {
  bucket                  = aws_s3_bucket.athena.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "athena" {
  bucket = aws_s3_bucket.athena.id
  rule {
    id     = "expire-query-results"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
  }
}

resource "aws_athena_workgroup" "this" {
  name          = local.name
  description   = "Data-transfer forensics over the VPC flow logs"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena.bucket}/results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
