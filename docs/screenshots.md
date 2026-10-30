# Screenshots

All 24 screenshots come from the build on 30 October 2026, in the order things happened. The account ID is masked as `<account-id>`. Times in the terminal output are UTC unless marked otherwise.

| # | What it shows |
|---|---|
| [01](screenshots/01-state-bucket-suffix-azs.png) | State bucket exists; the random bucket-name suffix; AZs offering t4g.small (us-east-1a, b, c, d, f); 0 Elastic IPs in use before the build |
| [02](screenshots/02-init-and-gates.png) | init with the S3 backend (AWS provider 6.71.0); fmt, validate, tflint clean; checkov 114 passed / 32 failed |
| [03](screenshots/03-base-apply-outputs.png) | End of the base apply outputs: the VPC in us-east-1a and us-east-1b, state list 48, the four bucket names |
| [04](screenshots/04-lab-status.png) | The output fix applied (`kit_aws.py fixed`), then: three instances OK with the same code hash; the NAT gateway's ENI and IP (10.170.0.151, use1-az1); the flow log ACTIVE with 25 fields; the first delivered file |
| [05](screenshots/05-payloads-and-idle.png) | The payloads built (1 GiB and 256 MiB, with hashes); the 240 s idle run |
| [06](screenshots/06-s3-through-nat.png) | 1 GiB from app-a and 256 MiB from app-b to S3 through the NAT gateway |
| [07](screenshots/07-cross-az-vs-same-az.png) | 1 GiB app-a → app-b (other AZ) and app-a → app-a2 (same AZ) |
| [08](screenshots/08-chatty-service.png) | The chatty service: 32,768 calls across AZs, then within one AZ (both "8.021 s": see the debugging journey) |
| [09](screenshots/09-inter-region-and-gzip.png) | 1 GiB to eu-west-1, then gzipped first: 1,073,741,824 → 300,144,888 bytes (0.2795), 44.07 s of CPU |
| [10](screenshots/10-internet-download.png) | 512 MiB downloaded from the internet through the NAT gateway |
| [11](screenshots/11-endpoint-plan.png) | The S3 gateway endpoint plan: `aws_vpc_endpoint.s3[0]` on the private route table |
| [12](screenshots/12-endpoint-plan-summary.png) | End of that plan: `Plan: 1 to add, 0 to change, 0 to destroy.` |
| [13](screenshots/13-s3-through-gateway-endpoint.png) | The same S3 uploads again, through the gateway endpoint |
| [14](screenshots/14-prices-first-attempt.png) | The first price fetch: no product for `USE1-EUW1-AWS-Out-Bytes`, so the cost model refuses to run (fixed with `USE1-EU-AWS-Out-Bytes`) |
| [15](screenshots/15-flow-logs-arrived.png) | 20 flow-log files delivered; 2,671 + 2,441 records over two hours, 4 ENIs; the flow logs cover the last run: YES |
| [16](screenshots/16-bytes-by-path.png) | Bytes by path over the whole build, and the idle background per instance |
| [17](screenshots/17-nat-legs.png) | The NAT gateway's ENI split into four legs per run, from the flow logs |
| [18](screenshots/18-nat-cloudwatch.png) | The NAT gateway's CloudWatch sums per run, next to the flow-log figures |
| [19](screenshots/19-stop-the-meter.png) | After stopping the meter: the NAT gateway `deleted`, state list 43 |
| [20](screenshots/20-cost-per-run.png) | What each run's bytes cost, per path |
| [21](screenshots/21-projection.png) | Mvelaphanda's month before and after the fixes, and the CloudFront check |
| [22](screenshots/22-summary-terraform.png) | The Terraform section of the summary: 44 added, 1 added, 6 destroyed |
| [23](screenshots/23-destroy-39.png) | `Destroy complete! Resources: 39 destroyed.` |
| [24](screenshots/24-clean-check.png) | Clean check: state list 0, nothing in us-east-1 or eu-west-1, an empty 581-byte state (time shown is local, +02:00) |
