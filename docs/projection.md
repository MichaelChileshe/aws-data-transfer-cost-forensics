# Mvelaphanda's month: before and after the fixes

The lab measures what each path costs per GB and how much the fixes remove. To turn that into a monthly bill I wrote a traffic profile for the company: [`profile/mvelaphanda-traffic.json`](../profile/mvelaphanda-traffic.json). **The profile is mine; the prices are AWS's; two numbers come from the lab.** Change the profile and rerun `python3 scripts/cost_model.py` to try other assumptions. Screenshot [`21`](screenshots/21-projection.png). Data: [`results/projection.json`](results/projection.json), [`results/projection.csv`](results/projection.csv).

## The profile (per month)

| What | Amount |
|---|---|
| Instances, AZs, NAT gateways today | 120, 2, 1 |
| S3 in the same Region (all through the NAT today) | 60 TB |
| Service-to-service calls (half of them across AZs today) | 100 TB |
| Replication to eu-west-1 (through the NAT today) | 30 TB |
| Internet egress / ingress | 40 TB / 15 TB |
| Share of NAT traffic coming from the other AZ | 0.5 |
| EC2 compute, for comparison | US$9,500 |

**From the lab:**
- **Compression ratio:** 0.2795, measured on the shipment CSV. Applied to 80% of the replication and egress bytes, as the compressible share, that's ×0.424.
- **Background through the NAT gateway:** 503,727 bytes an hour per instance, from the idle run. That's 0.040 TB a month for 120 instances.

## The bill

| Item | Before | | After | | Fix |
|---|---|---|---|---|---|
| | **TB** | **US$** | **TB** | **US$** | |
| NAT gateway hours | | 32.85 | | 65.70 | One NAT gateway per AZ (more hours) |
| NAT processing (S3 + replication + inbound + background) | 105.04 | 4,840.25 | 15.04 | 693.05 | S3 gateway endpoint; replication by S3 Cross-Region Replication, which doesn't pass through the NAT |
| Cross-AZ hop to the NAT gateway | 52.52 | 1,075.61 | 0 | 0.00 | A NAT gateway in every AZ |
| Service calls crossing AZs | 50.0 | 1,024.00 | 5.0 | 102.40 | AZ affinity: cross-AZ share 0.5 → 0.05 |
| S3 in the same Region | 60 | 0.00 | 60 | 0.00 | Always free |
| Inter-Region us-east-1 → eu-west-1 | 30 | 614.40 | 12.709 | 260.28 | Compression (×0.424) |
| Internet egress | 40 | 3,524.30 | 16.945 | 1,765.61 | Compression + CloudFront |
| Internet ingress | 15 | 0.00 | 15 | 0.00 | |
| **Total** | | **11,111.41** | | **2,887.04** | **Saves US$8,224.37 (74.0%)** |

Before the fixes, data transfer was **1.17 times** the EC2 compute bill.

## The CloudFront line is the one I'd change

The profile routes internet egress through CloudFront after the fixes, with South African viewers in mind. The model checks that against sending the same compressed bytes straight from us-east-1:
- **CloudFront (South Africa):** US$1,765.61 a month;
- **Straight from us-east-1:** US$1,517.59 a month.

CloudFront's first-tier price to South Africa (US$0.11/GB) is higher than us-east-1's internet price (US$0.09/GB). **Without CloudFront the "after" total is US$2,639.02, a saving of 76.2%.** CloudFront can still be the right call for caching (fewer bytes leaving the origin) and for latency to customers in South Africa. But the case has to be made on those grounds; on price per GB alone, it's dearer here.

## What the model leaves out

- **The NAT hours go up.** A NAT gateway per AZ doubles the hourly charge (US$32.85 → 65.70). That's worth it here because it removes the cross-AZ hop on 52.52 TB.
- **CloudFront's free tier** (1 TB a month) is included; request charges for CloudFront and S3 are not.
- **S3 Cross-Region Replication** still pays the inter-Region rate on what it copies, so that line keeps it. CRR's own replication request charges aren't modelled.
- **Internet egress doesn't go through the NAT gateway.** The profile assumes customers are served through public load balancers, so the 40 TB of egress pays internet transfer but no NAT processing. If it left from the private subnets, it would add about US$1,843 a month of NAT processing, plus a cross-AZ share.
- **List prices only.** No discounts, Savings Plans or private pricing.
