#!/usr/bin/env python3
"""Second source: the NAT gateway's own CloudWatch metrics (AWS/NATGateway, 1-minute Sums) per run
window, next to the NAT ENI legs the flow logs measured.

  python3 scripts/nat_metrics.py

Timestamps: the AWS CLI prints CloudWatch timestamps in the machine's LOCAL time zone (e.g. +02:00)
while EC2 and the run log use UTC/Unix seconds. Every timestamp is parsed with its offset and turned
into Unix seconds before anything is compared - never compared as text.
"""
import json
import sys
from datetime import datetime, timezone

from kit_aws import aws, lab_info, read_jsonl, read_result, write_result
from lab_runs import latest_runs

METRICS = ["BytesInFromSource", "BytesOutToDestination", "BytesInFromDestination", "BytesOutToSource"]


def to_epoch(ts):
    """Any ISO-8601 timestamp (Z, +00:00, +02:00, or naive = UTC) -> Unix seconds."""
    d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    info = lab_info()
    nat = info.get("nat")
    if not nat:
        sys.exit("no NAT gateway in build/results/lab.json: run scripts/lab_status.py while the lab is up")
    runs = latest_runs(read_jsonl("runs"))
    if not runs:
        sys.exit("no runs in build/results/runs.jsonl yet")
    start = int(min(r["t0"] for r in runs)) // 60 * 60 - 300
    end = int(max(r["t1"] for r in runs)) // 60 * 60 + 600
    queries = [{"Id": f"m{i}", "Label": m, "ReturnData": True, "MetricStat": {
        "Metric": {"Namespace": "AWS/NATGateway", "MetricName": m,
                   "Dimensions": [{"Name": "NatGatewayId", "Value": nat["id"]}]},
        "Period": 60, "Stat": "Sum"}} for i, m in enumerate(METRICS)]
    res = aws("cloudwatch", "get-metric-data", "--region", info["regions"]["primary"],
              "--metric-data-queries", json.dumps(queries), "--start-time", iso(start), "--end-time", iso(end),
              "--scan-by", "TimestampAscending")
    series = {}
    for r in res.get("MetricDataResults", []):
        pts = sorted((int(to_epoch(t)), v) for t, v in zip(r.get("Timestamps", []), r.get("Values", [])))
        series[r["Label"]] = pts
    if not any(series.values()):
        sys.exit("CloudWatch returned no NAT gateway datapoints yet: metrics can lag a few minutes; try again")

    # A 1-minute bucket [ts, ts+60) belongs to a run if it overlaps [t0, t1 + 60). With the quiet gap
    # between runs (150 s) no bucket can belong to two runs.
    per_run = {r["run"]: {m: 0.0 for m in METRICS} for r in runs}
    outside = {m: 0.0 for m in METRICS}
    for m, pts in series.items():
        for ts, v in pts:
            owner = next((r["run"] for r in runs if ts < r["t1"] + 60 and ts + 60 > r["t0"]), None)
            (per_run[owner] if owner else outside)[m] += v
    fl = (read_result("forensics") or {}).get("nat_legs", {})
    print(f"== NAT gateway {nat['id']} - CloudWatch Sums per run (bytes), flow-log NAT legs alongside")
    print(f"  {'run':<15} {'InFromSource':>14} {'OutToDest':>14} {'InFromDest':>14} {'OutToSource':>14} "
          f"{'processed CW':>14} {'processed FL':>14}")
    out = {}
    for name, v in list(per_run.items()) + [("(between runs)", outside)]:
        proc = v["BytesInFromSource"] + v["BytesInFromDestination"]
        flp = fl.get(name, {}).get("processed")
        out[name] = {**{m: int(x) for m, x in v.items()}, "processed": int(proc), "flowlog_processed": flp}
        flp_s = f"{flp:,}" if flp is not None else "-"
        print(f"  {name:<15} {v['BytesInFromSource']:>14,.0f} {v['BytesOutToDestination']:>14,.0f} "
              f"{v['BytesInFromDestination']:>14,.0f} {v['BytesOutToSource']:>14,.0f} {proc:>14,.0f} {flp_s:>14}")
    write_result("nat-metrics", {"nat_id": nat["id"], "start_utc": iso(start), "end_utc": iso(end),
                                 "per_run": out, "series": {m: [[iso(t), v] for t, v in p] for m, p in series.items()}})
    print("saved build/results/nat-metrics.json (processed = BytesInFromSource + BytesInFromDestination)")


if __name__ == "__main__":
    main()
