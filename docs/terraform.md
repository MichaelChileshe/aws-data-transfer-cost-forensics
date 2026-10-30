# Terraform

Everything in AWS is in [`infra/`](../infra/): one root module with a second AWS provider for eu-west-1. State lives in the shared bucket `nkosi-tfstate-<account id>` under `aws-data-transfer-cost-forensics/terraform.tfstate`, with S3-native locking. AWS provider **6.71.0** (constraint `~> 6.60`), locked in [`infra/.terraform.lock.hcl`](../infra/.terraform.lock.hcl).

| File | What it holds |
|---|---|
| `network.tf` | VPC 10.170.0.0/16; one public subnet and two private subnets (one per AZ, picked from the AZs that offer the instance type); IGW; **one NAT gateway** with its Elastic IP in AZ a; **one private route table for both AZs**; the optional S3 gateway endpoint |
| `compute.tf` | The instance role (SSM, plus writing objects to the two data buckets), a security group allowing ports 9000 and 8080 from inside the VPC only, and the three instances |
| `storage.tf` | The data lake (us-east-1) and the replica bucket (eu-west-1): Block Public Access, a TLS-only policy, objects expiring after a day |
| `forensics.tf` | The flow-log bucket and its delivery policy, the flow log (25 v5 fields, Parquet, hourly Hive partitions, 60 s), the Glue database and table with partition projection, and the Athena workgroup with its results bucket and 100 MiB scan limit |

## Phases

| Phase | Line in `infra/phases.auto.tfvars` | Plan / apply | State list |
|---|---|---|---|
| Base | (nothing) | `44 to add` | 48 (44 + 4 data sources: the AZs, the instance-type offerings, the AMI parameter, the caller identity) |
| S3 fix | `s3_gateway_endpoint = true` | `1 to add` | 49 |
| Stop the meter | `traffic_lab = false` | `6 destroyed`: the 3 instances, the NAT route, the NAT gateway, the Elastic IP | 43 |
| Destroy | | `39 destroyed` | 0 |

The base 44, from the apply log:
- S3 (15): 4 buckets, 4 Block Public Access settings, 4 lifecycle configurations, 3 bucket policies;
- network (14): VPC, 3 subnets, IGW, Elastic IP, NAT gateway, 2 route tables, 2 routes, 3 route table associations;
- compute (11): security group, 2 ingress rules, 1 egress rule, the role, its policy, the SSM attachment, the instance profile, 3 instances;
- forensics (4): the flow log, the Glue database and table, the Athena workgroup.

Logs: [`results/terraform/`](results/terraform/). Screenshots [`03`](screenshots/03-base-apply-outputs.png), [`11`](screenshots/11-endpoint-plan.png)–[`12`](screenshots/12-endpoint-plan-summary.png), [`19`](screenshots/19-stop-the-meter.png), [`22`](screenshots/22-summary-terraform.png), [`23`](screenshots/23-destroy-39.png).

## Design choices worth knowing

- **The "wrong" network is deliberate.** One NAT gateway and one private route table for two AZs is how many estates start, and it's the setup whose costs I wanted to measure. The fixes are measured against it, not built in from the start.
- **"Stop the meter" is a phase.** `traffic_lab = false` removes exactly what bills by the hour (the NAT gateway, its Elastic IP, the instances) as soon as the traffic is done. The flow-log data, Glue and Athena stay for the analysis. The NAT gateway took 53 s to delete.
- **Destroy order is designed, not left to chance.** The instances `depends_on` the NAT route, the public route, the route table associations, the egress rule, the role's policy and attachment, and the instance profile. Terraform creates all of those first and removes them last, so the instances still have their route and permissions while they shut down. In the stop-the-meter apply, the instances went (22–24 s), then the NAT route (1 s), the NAT gateway (53 s) and the Elastic IP (2 s).
- **The AZ IDs are discovered.** The subnets go into the first two AZs that offer the instance type. In my account that was us-east-1a (use1-az1) and us-east-1b (use1-az2).
- **The traffic tool travels in user data,** gzipped, and Terraform outputs its SHA-256. `lab_status.py` checked that every instance ran the same code (`ce7ccdec3d24114d`).
- **Bucket names carry a random suffix** made once on my machine (`infra/name.auto.tfvars`, not committed), never the account ID.
- **The flow-log bucket's policy** is the delivery policy from the VPC Flow Logs documentation (service principal with confused-deputy conditions). Terraform ignores later changes, because the flow-log service can rewrite it.

## Quality gates

`terraform fmt`, `validate` and `tflint` were clean. checkov: **114 passed, 32 failed** ([`results/terraform/checkov.txt`](results/terraform/checkov.txt), screenshot [`02`](screenshots/02-init-and-gates.png)). The scan covered `infra/` and `bootstrap/` (the state bucket).

| Finding | Count | Why it's like that here | In production |
|---|---|---|---|
| CKV_AWS_145 KMS encryption by default | 5 buckets | SSE-S3 for test data | SSE-KMS with a customer managed key |
| CKV_AWS_18 access logging | 5 | One-afternoon lab | Server access logs or CloudTrail data events |
| CKV_AWS_144 cross-region replication | 5 | The replica is copied by the drill, not by CRR | CRR where the DR plan needs it |
| CKV2_AWS_62 event notifications | 5 | Nothing consumes them | Only where something should react |
| CKV_AWS_21 versioning | 4 | Lab objects expire after 1 to 7 days | Versioning on real data |
| CKV_AWS_300 abort failed multipart uploads | 3 (state, flow logs, Athena results) | The data buckets have the rule | Add it everywhere |
| CKV_AWS_126 detailed monitoring / CKV_AWS_135 EBS-optimised | instances | Short lab, t4g.small | Detailed monitoring where alarms need 1-minute data |
| CKV2_AWS_19 Elastic IP not attached to an instance | the NAT's EIP | It belongs to the NAT gateway by design | Not a finding for a NAT gateway |
| CKV_AWS_394 AZ data source not pinned | `aws_availability_zones` | The subnets pick the first two AZs offering the type | Pin AZ IDs in a long-lived estate |
| CKV2_AWS_12 default security group | VPC | Unused, not emptied | Manage it with no rules |
