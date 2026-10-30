# The three app instances: "app-a" and "app-a2" in AZ a (same AZ as the NAT gateway), "app-b" in AZ b.
# Each runs mvela-svc (a TCP sink on 9000 and a small HTTP service on 8080) and carries the traffic
# generator. Commands arrive through SSM (the agent reaches SSM through the NAT gateway).

data "aws_ssm_parameter" "al2023_arm" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

data "aws_caller_identity" "current" {}

locals {
  apps = var.traffic_lab ? {
    "app-a"  = { subnet = "a", ip = cidrhost(local.private_subnets.a.cidr, 10) }
    "app-a2" = { subnet = "a", ip = cidrhost(local.private_subnets.a.cidr, 20) }
    "app-b"  = { subnet = "b", ip = cidrhost(local.private_subnets.b.cidr, 10) }
  } : {}
}

# ---- instance role: SSM, and writing objects to the two lab buckets ----

resource "aws_iam_role" "app" {
  name = "${local.name}-app-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "app_s3" {
  name = "${local.name}-app-s3"
  role = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteLabObjects"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
        Resource = ["${aws_s3_bucket.lake.arn}/*", "${aws_s3_bucket.replica.arn}/*"]
      },
      {
        Sid      = "ListLabBuckets"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.lake.arn, aws_s3_bucket.replica.arn]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name}-app-profile"
  role = aws_iam_role.app.name
}

# ---- security group: the two service ports from inside the VPC only; no admin ports ----

resource "aws_security_group" "app" {
  name        = "${local.name}-app-sg"
  description = "Mvelaphanda app services - 9000 (bulk TCP) and 8080 (HTTP) from inside the VPC only"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "${local.name}-app-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "bulk" {
  security_group_id = aws_security_group.app.id
  description       = "Bulk TCP transfers between app instances"
  ip_protocol       = "tcp"
  from_port         = 9000
  to_port           = 9000
  cidr_ipv4         = var.vpc_cidr
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.app.id
  description       = "Service-to-service HTTP calls (the chatty service)"
  ip_protocol       = "tcp"
  from_port         = 8080
  to_port           = 8080
  cidr_ipv4         = var.vpc_cidr
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.app.id
  description       = "Outbound: SSM, S3, the internet test download, the other app instances"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "app" {
  for_each = local.apps

  ami                    = data.aws_ssm_parameter.al2023_arm.insecure_value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.private[each.value.subnet].id
  private_ip             = each.value.ip
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 12
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/userdata.sh.tftpl", {
    name        = each.key
    code_gz_b64 = base64gzip(file("${path.module}/../app/mvela_traffic.py"))
  })
  user_data_replace_on_change = true

  tags = { Name = "${local.name}-${each.key}", AppName = each.key }

  # Created after, and destroyed BEFORE, everything the instance needs to boot, register with SSM and
  # shut down cleanly: the NAT route (and with it the NAT gateway and the IGW route), the egress rule,
  # and the role's policies.
  depends_on = [aws_route.private_nat, aws_route.public_internet, aws_route_table_association.private,
    aws_vpc_security_group_egress_rule.all, aws_iam_role_policy_attachment.app_ssm, aws_iam_role_policy.app_s3,
  aws_iam_instance_profile.app]

  lifecycle {
    ignore_changes = [ami]
  }
}
