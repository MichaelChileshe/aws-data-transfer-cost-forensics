# A small replica of Mvelaphanda's estate: the "classic" VPC. Private subnets in two AZs, one public
# subnet, ONE NAT gateway (in AZ a) that every private subnet uses for anything outside the VPC.

data "aws_availability_zones" "available" {
  state = "available"
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

# Only AZs that actually offer the instance type (some us-east-1 AZs don't offer every type).
data "aws_ec2_instance_type_offerings" "type" {
  location_type = "availability-zone"
  filter {
    name   = "instance-type"
    values = [var.instance_type]
  }
}

locals {
  name = "mvela-xfer"
  azs  = slice(sort(setintersection(data.aws_availability_zones.available.names, data.aws_ec2_instance_type_offerings.type.locations)), 0, 2)

  # private subnets: "a" = first AZ (same AZ as the NAT gateway), "b" = second AZ
  private_subnets = {
    a = { az = local.azs[0], cidr = cidrsubnet(var.vpc_cidr, 8, 10) }
    b = { az = local.azs[1], cidr = cidrsubnet(var.vpc_cidr, 8, 11) }
  }
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public_a" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 0)
  availability_zone = local.azs[0]
  tags              = { Name = "${local.name}-public-a" }
}

resource "aws_subnet" "private" {
  for_each          = local.private_subnets
  vpc_id            = aws_vpc.this.id
  cidr_block        = each.value.cidr
  availability_zone = each.value.az
  tags              = { Name = "${local.name}-private-${each.key}" }

  lifecycle {
    precondition {
      condition     = length(local.azs) == 2
      error_message = "Need two available AZs that offer ${var.instance_type}."
    }
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-public-rt" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

# ---- the ONE NAT gateway (zonal, AZ a) and its Elastic IP: the meter that runs per hour and per GB ----

resource "aws_eip" "nat" {
  count  = var.traffic_lab ? 1 : 0
  domain = "vpc"
  tags   = { Name = "${local.name}-nat-eip" }
}

resource "aws_nat_gateway" "this" {
  count         = var.traffic_lab ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public_a.id
  tags          = { Name = "${local.name}-nat-a" }

  depends_on = [aws_internet_gateway.this, aws_route.public_internet]
}

# One private route table for both private subnets (the classic setup): everything that isn't the
# VPC goes to the NAT gateway in AZ a, even from AZ b.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-private-rt" }
}

resource "aws_route" "private_nat" {
  count                  = var.traffic_lab ? 1 : 0
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

# ---- phase: the S3 gateway endpoint (no hourly or per-GB charge). It adds a route to the S3
# prefix list for this Region on the private route table; S3 in OTHER Regions still uses the NAT. ----

resource "aws_vpc_endpoint" "s3" {
  count             = var.s3_gateway_endpoint ? 1 : 0
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "${local.name}-s3-gateway" }
}
