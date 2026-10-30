# Teardown and clean check

Nothing of this project should exist or bill after the afternoon, except the shared state bucket.

## Stop the meter (before the analysis)

As soon as the last run was done, `traffic_lab = false` removed what bills by the hour: `0 added, 0 changed, 6 destroyed`, leaving 43 in state.
- **Removed:** the three instances (22–24 s), the NAT route (1 s), the NAT gateway (53 s) and its Elastic IP (2 s).
- **Kept:** the flow-log data, Glue and Athena, for the analysis.

Screenshot [`19`](screenshots/19-stop-the-meter.png) shows the NAT gateway `deleted` and the state count 43.

## Destroy

`terraform -chdir=infra destroy`: `Plan: 0 to add, 0 to change, 39 to destroy.` → **`Destroy complete! Resources: 39 destroyed.`** Log: [`results/terraform/tf-destroy.txt`](results/terraform/tf-destroy.txt). Screenshot [`23`](screenshots/23-destroy-39.png).

All four buckets have `force_destroy`, so Terraform emptied them first: the flow logs, the Athena results, and the uploaded test files in both Regions. A late flow-log file arriving while the bucket was emptied could have failed it with `BucketNotEmpty`; the logged destroy has no error. 44 + 1 resources were created and 6 + 39 destroyed.

## Clean check (both Regions)

Screenshot [`24`](screenshots/24-clean-check.png).

| Check | Result |
|---|---|
| `terraform state list` | **0** |
| us-east-1 and eu-west-1: instances, NAT gateways (not `deleted`), Elastic IPs, VPC endpoints, flow logs, VPCs with the project tag | nothing under either Region heading |
| Buckets `mvela-xfer*`, Glue database `mvela_xfer`, Athena workgroup `mvela-xfer`, IAM roles and instance profiles `mvela-xfer*` | nothing (these checks print nothing when empty, so the screenshot shows no line for them) |
| State object | `terraform.tfstate`, **581 bytes** (an empty state), written 14:54:33 local time (12:54:33 UTC) |

## The next day

`scripts/ce_usage.py` reads Cost Explorer for 30 October 2026, grouped by service and usage type (one request, US$0.01). It puts the billed GB next to the measured GB:
- `NatGateway-Bytes` against the NAT gateway's processed bytes;
- `DataTransfer-Regional-Bytes` against twice the cross-AZ hop bytes (both sides are billed);
- `USE1-EU-AWS-Out-Bytes` against the flow logs to eu-west-1.
