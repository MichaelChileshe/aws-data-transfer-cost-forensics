output "phases" {
  description = "Which phases are on right now."
  value       = { traffic_lab = var.traffic_lab, s3_gateway_endpoint = var.s3_gateway_endpoint }
}

output "regions" {
  description = "Primary and second Region."
  value       = { primary = var.region, second = var.second_region }
}

output "vpc" {
  description = "The lab VPC: ID, CIDR, the two AZs used."
  value       = { id = aws_vpc.this.id, cidr = var.vpc_cidr, azs = local.azs }
}

output "lab" {
  description = "Per app instance: ID, private IP, ENI, AZ name and AZ ID (empty when traffic_lab = false)."
  value = { for k, v in aws_instance.app : k => {
    id         = v.id
    private_ip = v.private_ip
    eni        = v.primary_network_interface_id
    az         = v.availability_zone
    az_id      = aws_subnet.private[local.apps[k].subnet].availability_zone_id
    subnet     = local.apps[k].subnet
  } }
}

output "nat" {
  description = "The NAT gateway: ID, its ENI and private IP (what the flow logs show), public IP, AZ ID. null when traffic_lab = false."
  value = var.traffic_lab ? {
    id         = aws_nat_gateway.this[0].id
    eni        = aws_nat_gateway.this[0].network_interface_id
    private_ip = aws_nat_gateway.this[0].private_ip
    public_ip  = aws_nat_gateway.this[0].public_ip
    az_id      = aws_subnet.public_a.availability_zone_id
  } : null
}

output "s3_gateway_endpoint_id" {
  description = "The S3 gateway endpoint (null until the phase is on)."
  value       = var.s3_gateway_endpoint ? aws_vpc_endpoint.s3[0].id : null
}

output "buckets" {
  description = "Bucket names: data lake (primary), replica (second Region), flow logs, Athena results."
  value = {
    lake     = aws_s3_bucket.lake.bucket
    replica  = aws_s3_bucket.replica.bucket
    flowlogs = aws_s3_bucket.flowlogs.bucket
    athena   = aws_s3_bucket.athena.bucket
  }
}

output "flow_log_id" {
  description = "The VPC flow log."
  value       = aws_flow_log.vpc.id
}

output "athena" {
  description = "Where the forensics queries run."
  value = {
    workgroup = aws_athena_workgroup.this.name
    database  = aws_glue_catalog_database.this.name
    table     = aws_glue_catalog_table.flows.name
    flow_root = "${local.flow_prefix}/"
  }
}

output "app_sha256" {
  description = "SHA-256 of app/mvela_traffic.py: compare with the file on an instance."
  value       = filesha256("${path.module}/../app/mvela_traffic.py")
}
