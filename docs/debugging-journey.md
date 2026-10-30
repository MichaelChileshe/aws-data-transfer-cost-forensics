# Debugging journey

The traffic, the flow logs and the teardown all behaved. What broke was in my own tooling, and each problem was caught by a script refusing to carry on, or by checking results that looked too neat.

## 1. "terraform output is missing ['s3_gateway_endpoint_id']"

**What I saw.** The first status check after the base apply stopped with:

```
terraform output is missing ['s3_gateway_endpoint_id']: has the base apply run?
```

The base apply had run (44 added, state list 48).

**Why.** `terraform output -json` **leaves out any output whose value is null**. The endpoint output is `null` until its phase is on, so it wasn't missing: it was off. Once the meter is stopped, the NAT gateway output becomes null the same way (and the instances output becomes an empty map), so the same error would have hit later.

**The fix** ([`scripts/kit_aws.py`](../scripts/kit_aws.py)): those three outputs are optional, and absent means `None`. I patched it in place and reran; screenshot [`04`](screenshots/04-lab-status.png) starts with that patch's `kit_aws.py fixed` line.

**Lesson:** in Terraform's JSON output, "absent" and "null" are the same thing.

## 2. The inter-Region prices didn't resolve

**What I saw.** `prices.py` printed (screenshot [`14`](screenshots/14-prices-first-attempt.png)):

```
PRICES MISSING OR AMBIGUOUS - the cost model will not run until these are fixed:
  - use1_to_euw1_gb: no product matches {'usagetype': 'USE1-EUW1-AWS-Out-Bytes'} in ['AWSDataTransfer', 'AmazonEC2']
  - euw1_to_use1_gb: no product matches {'usagetype': 'EUW1-USE1-AWS-Out-Bytes'} in ['AWSDataTransfer', 'AmazonEC2']
```

and `cost_model.py` refused to run. That refusal is deliberate: after the last project, where a lookup silently took the first of several products, a missing or ambiguous price stops everything.

**Why.** Billing usage types use each Region's billing code. eu-west-1's is the old **`EU`**, not `EUW1`, so the usage types are `USE1-EU-AWS-Out-Bytes` and `EU-USE1-AWS-Out-Bytes`.

**The fix.** I reran the lookup with the right usage types as a one-off override (`--pin use1_to_euw1_gb:usagetype=USE1-EU-AWS-Out-Bytes`, and the same for the return direction). Each matched exactly one product: SKU `NW4B786HNAH6HZ7R` at US$0.02/GB from US East (N. Virginia), and `N7JF33XCBEZEKJFQ` at US$0.02/GB from EU (Ireland). The names are now fixed in [`scripts/prices.py`](../scripts/prices.py) and [`scripts/ce_usage.py`](../scripts/ce_usage.py), so tomorrow's Cost Explorer comparison looks for the right usage type.

`results/prices.txt` is the first attempt's output. `results/prices.json` (fetched 12:51:09 UTC) is the corrected one, and every number in the cost model comes from it.

**Also removed:** two optional lookups for interface-endpoint prices (`VpcEndpoint-Hours`, `VpcEndpoint-Bytes` under `AmazonVPC`) matched nothing. Nothing used them, so I dropped them rather than keep lookups that always fail.

## 3. Both chatty runs took "exactly 8.021 s"

**What I saw.** The cross-AZ and same-AZ chatty runs both reported 8.021 s and 4,085.4 calls a second. Two runs on different paths agreeing to the millisecond is too neat.

**Why.** The tool's main thread checked every **0.5 s** whether its 8 workers had finished, and took the end time when it noticed. Every chatty duration could only land on a 0.5 s step (plus a few ms): both runs finished somewhere between 7.5 and 8.0 s, and both were reported as the end of that step.

**What it affected.** Only the duration and the calls-per-second figure. The byte counts come from the workers themselves and are exact, so every byte and cost figure stands.

**The fix** ([`app/mvela_traffic.py`](../app/mvela_traffic.py)): each worker records when it finishes, and the run ends at the last one. Tested locally: 2,000 calls reported 0.266 s, not a 0.5 s step. Because the file changed, its SHA-256 no longer matches the `ce7ccdec3d24114d` the instances reported during the build; that was the version before this fix.

**Lesson:** when two measurements agree too perfectly, look at how the clock is read.

## 4. Open question: traffic between the runs

Outside the run windows, each instance recorded about 120 MB arriving from S3 addresses, and I haven't identified the source. Over the same window the NAT gateway's ENI recorded only 170.3 MB in from destinations, against the instances' 362 MB, so this traffic doesn't reconcile the way the runs do ([details](forensics.md)). It doesn't affect any per-run number, and the per-minute flow records would be where I'd look next.

## Things I checked that were fine

- **Every private IP's AZ, learned from the flow logs, matched Terraform:** four of four.
- **The flow logs covered the last run** before the analysis ran: last record 12:28:26, last run ended 12:27:55.
- **The NAT gateway's CloudWatch metrics agreed with the flow logs within 0.13%** for every run that moved real data through it ([cross-check](nat-cross-check.md)).
- **Every instance ran the same traffic code,** by SHA-256.
- **The account ID is masked** everywhere in the results and screenshots: the pack script masked the results and refused to pack if any were left; the screenshots were masked separately.
