variable "region" {
  description = "Primary Region: the replica of Mvelaphanda's estate (VPC, NAT, instances, data lake, forensics)."
  type        = string
  default     = "us-east-1"
}

variable "second_region" {
  description = "Second Region: the replica bucket that receives the inter-Region copies."
  type        = string
  default     = "eu-west-1"
}

variable "name_suffix" {
  description = "Random suffix that makes the bucket names globally unique. Generated once into infra/name.auto.tfvars (gitignored); never derived from the account ID."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{6,12}$", var.name_suffix))
    error_message = "name_suffix: 6-12 lowercase letters/digits (generate it once: see the README)."
  }
}

variable "vpc_cidr" {
  description = "The lab VPC. Subnets: public-a .0.0/24, private-a .10.0/24, private-b .11.0/24."
  type        = string
  default     = "10.170.0.0/16"
}

variable "instance_type" {
  description = "Graviton (arm64) type for app-a, app-a2 and app-b. t4g.small or larger."
  type        = string
  default     = "t4g.small"

  validation {
    condition     = can(regex("^(t4g|m7g|c7g|m6g|c6g)\\.", var.instance_type)) && !endswith(var.instance_type, ".nano") && !endswith(var.instance_type, ".micro")
    error_message = "Use a Graviton type of size small or larger (never nano/micro)."
  }
}

variable "athena_bytes_scanned_cutoff" {
  description = "Athena workgroup guard rail: any single query that would scan more than this many bytes is cancelled (minimum 10 MB)."
  type        = number
  default     = 104857600 # 100 MiB; the lab's flow logs are a few MB
}

# ---- phases: change in infra/phases.auto.tfvars, then apply ----

variable "traffic_lab" {
  description = "true = the three instances, the NAT gateway, its Elastic IP and the NAT route exist (the traffic runs). false = only the forensics side stays (flow log data, Athena, buckets): 'stop the meter'."
  type        = bool
  default     = true
}

variable "s3_gateway_endpoint" {
  description = "The fix for S3 traffic: an S3 gateway endpoint on the private route table, so same-Region S3 traffic stops going through the NAT gateway."
  type        = bool
  default     = false
}
