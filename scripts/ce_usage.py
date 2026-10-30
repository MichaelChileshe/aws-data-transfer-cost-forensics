#!/usr/bin/env python3
"""The billing view, the day AFTER the build: Cost Explorer cost and usage for the build day(s),
grouped by service and usage type, next to what the flow logs measured.

  python3 scripts/ce_usage.py                      # the UTC day(s) the runs happened (from runs.jsonl)
  python3 scripts/ce_usage.py --date 2026-10-30    # a specific UTC day
  python3 scripts/ce_usage.py --date 2026-10-30 --days 2

Cost Explorer's API is in us-east-1 and costs US$0.01 per request (each page is a request); this
script normally makes ONE. Usage can take up to 24 hours to appear. US East (N. Virginia) usage
types have no Region prefix (NatGateway-Bytes, DataTransfer-Regional-Bytes, DataTransfer-Out-Bytes);
inter-Region ones name both Regions (USE1-EU-AWS-Out-Bytes, EU-USE1-AWS-In-Bytes; eu-west-1's billing code is EU).
"""
import re
import sys
from datetime import date, datetime, timedelta, timezone

from kit_aws import aws, read_jsonl, read_result, write_result
from lab_runs import latest_runs

GB = float(1 << 30)
WATCH = re.compile(r"(NatGateway|DataTransfer|AWS-Out|AWS-In|VpcEndpoint|C3DataTransfer|VendedLog|S3-Egress|"
                   r"DataScanned|BoxUsage:t4g)")


def main():
    args = sys.argv[1:]
    days = int(args[args.index("--days") + 1]) if "--days" in args else None
    if "--date" in args:
        start = date.fromisoformat(args[args.index("--date") + 1])
    else:
        runs = latest_runs(read_jsonl("runs"))
        if not runs:
            sys.exit("no runs.jsonl: pass --date YYYY-MM-DD")
        first = datetime.fromtimestamp(min(r["t0"] for r in runs), timezone.utc).date()
        last = datetime.fromtimestamp(max(r["t1"] for r in runs), timezone.utc).date()
        start, days = first, days or (last - first).days + 1
    days = days or 1
    end = start + timedelta(days=days)
    if end > datetime.now(timezone.utc).date() + timedelta(days=1):
        sys.exit(f"{start} .. {end} is in the future (UTC)")
    groups, token, requests = [], None, 0
    while True:
        cmd = ["ce", "get-cost-and-usage", "--region", "us-east-1", "--time-period",
               f"Start={start.isoformat()},End={end.isoformat()}", "--granularity", "DAILY",
               "--metrics", "UnblendedCost", "UsageQuantity",
               "--group-by", "Type=DIMENSION,Key=SERVICE", "Type=DIMENSION,Key=USAGE_TYPE"]
        if token:
            cmd += ["--next-page-token", token]
        res = aws(*cmd)
        requests += 1
        for day in res.get("ResultsByTime", []):
            for g in day.get("Groups", []):
                groups.append({"day": day["TimePeriod"]["Start"], "service": g["Keys"][0], "usage_type": g["Keys"][1],
                               "usd": float(g["Metrics"]["UnblendedCost"]["Amount"]),
                               "quantity": float(g["Metrics"]["UsageQuantity"]["Amount"]),
                               "unit": g["Metrics"]["UsageQuantity"].get("Unit")})
        token = res.get("NextPageToken")
        if not token or requests >= 5:
            break
    print(f"== Cost Explorer {start} -> {end} (End exclusive, UTC days), {requests} request(s) = US${requests * 0.01:.2f}")
    if not groups:
        print("  no usage yet: Cost Explorer can take up to 24 hours. Try again later.")
    watch = [g for g in groups if WATCH.search(g["usage_type"])]
    for g in sorted(watch, key=lambda g: (g["day"], -g["usd"])):
        print(f"  {g['day']}  {g['service'][:34]:<34} {g['usage_type']:<34} {g['quantity']:>14,.6f} {g['unit'] or '':<8} "
              f"US${g['usd']:.4f}")
    other = sum(g["usd"] for g in groups if g not in watch)
    print(f"  (+ {len(groups) - len(watch)} other usage types, US${other:.4f}: other projects that day count too)")

    fx = read_result("forensics") or {}
    if fx:
        nat = sum(v["processed"] for k, v in fx.get("nat_legs", {}).items()) / GB
        xaz = sum(h["bytes"] for h in fx.get("hops", []) if h["kind"] == "cross-AZ") / GB
        eu = sum(p["bytes"] for p in fx.get("paths_by_run", []) if "eu-west-1" in p["path"] and p["direction"] == "egress") / GB

        def q(pattern):
            return sum(g["quantity"] for g in groups if re.fullmatch(pattern, g["usage_type"]))
        print("\n== Bill vs flow logs (GB)")
        print(f"  NatGateway-Bytes             billed {q('NatGateway-Bytes'):>10.3f}   flow logs (NAT processed) {nat:>10.3f}")
        print(f"  DataTransfer-Regional-Bytes  billed {q('DataTransfer-Regional-Bytes'):>10.3f}   "
              f"flow logs cross-AZ hops {xaz:>10.3f} x 2 sides = {xaz * 2:>10.3f}")
        print(f"  USE1-EU-AWS-Out-Bytes        billed {q('USE1-EU-AWS-Out-Bytes'):>10.3f}   flow logs to eu-west-1 {eu:>10.3f}")
    write_result(f"ce-{start.isoformat()}", {"start": start.isoformat(), "end": end.isoformat(), "requests": requests,
                                             "groups": groups})
    print(f"saved build/results/ce-{start.isoformat()}.json")


if __name__ == "__main__":
    main()
