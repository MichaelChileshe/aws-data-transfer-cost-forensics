# The forensics: from flow records to a cost per path

Cost tools tell you how many GB were billed under `NatGateway-Bytes` or `DataTransfer-Regional-Bytes`. They don't tell you which service sent them, to where, or why they went through the NAT gateway. VPC Flow Logs can, if they record the right fields and the analysis is careful about what each record means.

## What the flow log records

One flow log on the whole VPC, so every ENI is covered, including the NAT gateway's. Screenshot [`04`](screenshots/04-lab-status.png).

- **Status:** `ACTIVE`, delivery `SUCCESS`, traffic type `ALL`.
- **Aggregation:** 60 s (the default is 10 minutes, too coarse to separate runs).
- **Destination:** S3, as Parquet with Hive-compatible paths and hourly partitions.
- **25 fields, version 5:**

```
version account-id interface-id srcaddr dstaddr srcport dstport protocol packets bytes start end action
log-status vpc-id subnet-id instance-id az-id sublocation-type flow-direction traffic-path
pkt-src-aws-service pkt-dst-aws-service pkt-srcaddr pkt-dstaddr
```

The fields beyond the default format are what make this work:
- `flow-direction` says whether a record is ingress or egress on that ENI;
- `traffic-path` says how egress left: through an internet gateway, a NAT gateway, a gateway endpoint, and so on;
- `az-id` is the AZ of the ENI that captured the record;
- `pkt-src-aws-service` / `pkt-dst-aws-service` name the AWS service on the other end (S3, EC2, AMAZON).

A Glue table with **partition projection** over the year/month/day/hour folders lets Athena read the files without a crawler or `MSCK REPAIR`. The Athena workgroup `mvela-xfer` cancels any single query that would scan more than 100 MiB. The six queries (the delivery check and five analysis queries) scanned **639,774 bytes** in total.

Before the analysis, `forensics.py check` confirmed the delivery: 2,671 records in hour 11 and 2,441 in hour 12 (UTC), 4 ENIs, and the last record ending at 12:28:26, after the last run ended at 12:27:55. Screenshot [`15`](screenshots/15-flow-logs-arrived.png).

## The runs

Each run is one command line on one instance, through SSM (gzip-euw1 chains the gzip and the upload). The tool sends an exact number of payload bytes and logs its start and end times. `run_traffic.py` leaves **150 s** between runs, so each run's flow records fall in a window of their own. Data: [`results/runs.jsonl`](results/runs.jsonl).

| Run (UTC start) | From → to | Payload bytes | Seconds |
|---|---|---|---|
| idle (11:48:39) | app-a: nothing for 240 s | 0 | 240.011 |
| s3-nat (11:55:36) | app-a → S3 us-east-1, through the NAT | 1,073,741,824 | 3.747 |
| s3-nat-from-b (11:58:19) | app-b (AZ b) → S3 us-east-1, through the NAT in AZ a | 268,435,456 | 1.801 |
| xaz-bulk (12:01:00) | app-a → app-b, TCP, other AZ | 1,073,741,824 | 1.953 |
| saz-bulk (12:03:42) | app-a → app-a2, TCP, same AZ | 1,073,741,824 | 1.730 |
| chatty-xaz (12:06:23) | app-a → app-b, 32,768 HTTP calls (4 KiB request, 1 KiB answer), 8 workers | 167,772,160 | 7.5–8.0 * |
| chatty-saz (12:09:10) | app-a → app-a2, the same calls | 167,772,160 | 7.5–8.0 * |
| s3-euw1-nat (12:11:54) | app-a → S3 eu-west-1, through the NAT | 1,073,741,824 | 7.378 |
| gzip-euw1 (12:15:21) | the same file gzipped on app-a, then → S3 eu-west-1 | 300,144,888 | 3.635 |
| internet-in (12:18:28) | public HTTPS server → app-a, through the NAT | 536,870,912 | 12.530 |
| *(S3 gateway endpoint applied)* | | | |
| s3-gwe (12:24:59) | app-a → S3 us-east-1, through the gateway endpoint | 1,073,741,824 | 7.376 |
| s3-gwe-from-b (12:27:54) | app-b → S3 us-east-1, through the gateway endpoint | 268,435,456 | 1.563 |

\* Both chatty runs reported 8.021 s because the tool only checked every 0.5 s whether its workers had finished ([debugging journey](debugging-journey.md)). Their byte counts are exact.

The payloads are a deterministic CSV of shipment events built on the instances: 1 GiB on app-a (sha256 `1765d8a551069ec1…`) and 256 MiB on app-b (`4ff50806caa819a8…`).

## Classifying every record

All six queries share [`sql/_base.sql`](../sql/_base.sql). The filled-in copies that ran are in [`results/sql/`](results/sql/).

1. **Which AZ is each private IP in?** It's learned from the flow logs themselves, never assumed. On any ENI, the source of an egress record and the destination of an ingress record are that ENI's own IP, and `az-id` is that ENI's AZ. The result for all four IPs matched Terraform: 10.170.10.10 and 10.170.10.20 in use1-az1, 10.170.11.10 in use1-az2, and the NAT gateway's 10.170.0.151 in use1-az1.
2. **Which path did each conversation take?** `traffic-path` exists only on egress records, so the query copies it to the ingress records of the same connection. That way a download also gets a route. The peer is labelled by AWS service, or as the internet.
3. **Cross-AZ hops, each counted once.**
   - Instance to instance: the sender's egress record.
   - Instance to the NAT gateway: the **NAT gateway's** record. The instance's own record shows the final destination (S3, say), so the hop to the NAT gateway is only visible on the NAT's ENI.
   - NAT gateway back to the instance: also the NAT gateway's record.
4. **The NAT gateway's four legs,** in the same split CloudWatch uses:
   - in from source (instances → NAT);
   - out to destination;
   - in from destination;
   - out to source.

   **Processed** = in from source + in from destination. That is what `NatGateway-Bytes` bills.

## Reconciliation: sent vs measured

Measured on the sender's ENI, for the path each run was meant to use (the whole-build path totals are in screenshot [`16`](screenshots/16-bytes-by-path.png)). Data: [`results/forensics.json`](results/forensics.json).

| Run | Expected path | Sent | Measured | Ratio | Bytes / packet | Cross-AZ hop bytes | NAT processed |
|---|---|---|---|---|---|---|---|
| s3-nat | S3 us-east-1 via NAT | 1,073,741,824 | 1,092,453,029 | 1.0174 | 3,572 | 14,236 | 1,097,533,089 |
| s3-nat-from-b | S3 us-east-1 via NAT | 268,435,456 | 276,321,282 | 1.0294 | 2,671 | **275,161,240** | 275,172,289 |
| xaz-bulk | cross-AZ | 1,073,741,824 | 1,080,125,900 | 1.0059 | 8,999 | **1,080,648,611** | 39,399 |
| saz-bulk | same-AZ | 1,073,741,824 | 1,080,080,323 | 1.0059 | 9,000 | 13,927 | 62,462 |
| chatty-xaz | cross-AZ, both ways | 167,772,160 | 187,682,432 | 1.1187 | 953 | **187,696,766** | 41,419 |
| chatty-saz | same-AZ, both ways | 167,772,160 | 187,665,792 | 1.1186 | 953 | 2,389 | 28,291 |
| s3-euw1-nat | S3 eu-west-1 via NAT | 1,073,741,824 | 1,117,620,072 | 1.0409 | 1,456 | 30,225 | 1,120,817,728 |
| gzip-euw1 | S3 eu-west-1 via NAT | 300,144,888 | 312,264,641 | 1.0404 | 1,457 | 17,571 | 314,018,431 |
| internet-in | internet via NAT, inbound | 536,870,912 | 556,956,868 | 1.0374 | 1,499 | 2,124 | 558,929,849 |
| s3-gwe | S3 us-east-1 via gateway endpoint | 1,073,741,824 | 1,093,553,357 | 1.0185 | 3,720 | 13,973 | 39,361 |
| s3-gwe-from-b | S3 us-east-1 via gateway endpoint | 268,435,456 | 274,401,680 | 1.0222 | 3,114 | 10,205 | 26,306 |

**What the reconciliation shows:**
- **Every run landed on the path it was meant to use,** and the measured bytes are the payload plus protocol overhead. The overhead is 0.6% for bulk TCP between instances with jumbo frames (about 9,000 bytes a packet), 1.7–4.1% for HTTPS to S3 and the internet (1,456–3,720 bytes a packet), and **12%** for the chatty service, whose 953-byte average packets carry HTTP headers on every call.
- **The receiver saw the same bytes.** For the bulk runs, app-b's and app-a2's ENIs recorded 1,079,981,884 and 1,079,981,312 bytes arriving. For the chatty runs the receivers recorded the requests (144.2 million bytes); the answers are on the sender's side.
- **The cross-AZ hops are where they should be.**
  - **1.08 GB** for xaz-bulk and **187.7 MB** for chatty-xaz.
  - **275.2 MB** for s3-nat-from-b, which is app-b's upload crossing to the NAT gateway in AZ a.
  - After the gateway endpoint, s3-gwe-from-b had **10,205 bytes**: the hop is gone. The same-AZ runs show only a few KB of background.
- **With the gateway endpoint the NAT gateway saw only background** (39,361 and 26,306 bytes, about what it saw during idle and the instance-to-instance runs).

## Outside the runs

Outside the run windows, each instance's ENI recorded about **120 MB arriving from S3 addresses** (121.6, 120.0 and 120.1 MB; the largest single flows were about 80 MB each). My traffic tool and boot script don't download anything, so this came from something else on the instances, and I haven't identified what.

It also doesn't reconcile the way the runs do. Over the same window, the NAT gateway's ENI recorded **170.3 MB** in from destinations outside the runs, less than the 362 MB the instances recorded. That's an open question I'd chase next, with the per-minute records showing when each flow happened. It doesn't touch any per-run figure: keeping between-run traffic out is exactly what the run windows are for. It does show up in the whole-build path totals ([`results/forensics.txt`](results/forensics.txt)), for example "S3 us-east-1 via NAT gateway, ingress, 367,996,943".

During the 240 s idle run, the background was 398 KB to 662 KB an hour per instance, all of it to AWS service addresses through the NAT gateway. Across 120 instances that's about 0.04 TB a month: real, but small next to everything else.
