# Paths and what they cost

## The prices

Every price comes from the **AWS Price List API** (`pricing get-products`), and each lookup has to match **exactly one product**: more than one match is an error, and the cost model won't run with a missing price. The final fetch was at 12:51:09 UTC. Data: [`results/prices.json`](results/prices.json), every raw record in [`results/prices-raw.json`](results/prices-raw.json).

| Price | Usage type | US$ |
|---|---|---|
| NAT gateway, per hour | `NatGateway-Hours` | 0.045 |
| NAT gateway, per GB processed | `NatGateway-Bytes` | 0.045 |
| Between AZs in us-east-1, per GB, **charged on each side** | `DataTransfer-Regional-Bytes` | 0.01 |
| us-east-1 → eu-west-1, per GB | `USE1-EU-AWS-Out-Bytes` | 0.02 |
| eu-west-1 → us-east-1, per GB (S3's answers coming back) | `EU-USE1-AWS-Out-Bytes` | 0.02 |
| us-east-1 → internet, per GB | `DataTransfer-Out-Bytes` | 0.09 for the first 10 TB, then 0.085, 0.07, 0.05 |
| Internet → us-east-1 | `DataTransfer-In-Bytes` | 0.00 |
| CloudFront to viewers in South Africa, per GB | `ZA-DataTransfer-Out-Bytes` | 0.11 for the first 10 TB, falling to 0.04 |
| CloudFront to viewers in the United States, per GB | `US-DataTransfer-Out-Bytes` | 0.085 for the first 10 TB, falling to 0.02 |

Three facts come from AWS's pricing pages rather than the Price List (the first and third are also noted in `prices.json`):
- an **S3 gateway endpoint** has no hourly or per-GB charge;
- S3 traffic to an instance in the **same Region** has no transfer charge;
- the **first 100 GB a month** to the internet are free, across all Regions and services.

The first fetch failed for the two inter-Region prices (screenshot [`14`](screenshots/14-prices-first-attempt.png)). The fix is in [the debugging journey](debugging-journey.md). `results/prices.txt` is that first attempt's output; `prices.json` is from the corrected fetch.

## Cost of each run

From the measured bytes of each path, not the payload. Screenshot [`20`](screenshots/20-cost-per-run.png). Data: [`results/cost-runs.csv`](results/cost-runs.csv).

| Run | NAT | Cross-AZ | Inter-Region | Internet out | **Total** | Per GB sent |
|---|---|---|---|---|---|---|
| s3-nat | 0.0460 | | | | **0.0460** | 0.0460 |
| s3-nat-from-b | 0.0115 | 0.0051 | | | **0.0167** | 0.0666 |
| xaz-bulk | | 0.0201 | | | **0.0201** | 0.0201 |
| saz-bulk | | | | | **0.0000** | 0.0000 |
| chatty-xaz | | 0.0035 | | | **0.0035** | 0.0224 |
| chatty-saz | | | | | **0.0000** | 0.0000 |
| s3-euw1-nat | 0.0470 | | 0.0209 | | **0.0679** | 0.0679 |
| gzip-euw1 | 0.0132 | | 0.0058 | | **0.0190** | 0.0680 (per compressed GB) |
| internet-in | 0.0234 | | | 0.0002 | **0.0236** | 0.0472 |
| s3-gwe | | | | | **0.0000** | 0.0000 |
| s3-gwe-from-b | | | | | **0.0000** | 0.0000 |
| idle | | | | | 0.0000 | |

Data charges for all twelve runs: **US$0.1967**. NAT gateway hours, estimated at two billed hours: US$0.0900. Internet out is priced at the first paid tier for comparison; a lab this size sits inside the free 100 GB a month.

## What each comparison shows

- **S3 in the same Region: the NAT gateway is the whole cost.** S3 transfer within the Region is free; the US$0.046 for 1 GiB is entirely NAT processing. Through the gateway endpoint the same upload cost nothing, and the NAT gateway saw only background (39,361 bytes).
- **The NAT gateway in "the other" AZ costs twice.** app-b's 256 MiB upload paid NAT processing **and** a cross-AZ hop to AZ a, so US$0.0666 per GB sent instead of US$0.046. With the gateway endpoint, both charges went.
- **Cross-AZ is billed on both sides.** 1 GiB from AZ a to AZ b cost US$0.0201 (US$0.01 out of one AZ, US$0.01 into the other). The same GiB inside one AZ cost nothing.
- **Chatty traffic pays the same rate, plus its overhead.** The 32,768 calls moved 160 MiB of payload, but the wire carried 12% more, all billable across AZs. Keeping the caller and the service in the same AZ cost nothing.
- **Inter-Region pays twice when it goes through a NAT gateway:** US$0.045 NAT processing plus US$0.02 inter-Region. Compressing first made the file 0.2795 of its size, so the copy cost **72% less** (US$0.0190 against US$0.0679). The price is 44 s (elapsed) on a t4g.small to gzip 1 GiB.
- **Inbound from the internet is free; the NAT gateway in front of it isn't.** The 512 MiB download cost US$0.0234, all NAT processing.

A note on the S3 uploads' speed: the run through the gateway endpoint took 7.376 s and the first run through the NAT 3.747 s. The eu-west-1 copy (7.378 s) and the gateway-endpoint upload ran at almost the same rate, about 1,164 Mbit/s. t4g.small network bandwidth is burstable, so I don't read anything about the endpoint's speed into one upload each.
