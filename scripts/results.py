#!/usr/bin/env python3
"""Every measured number from build/results/ in one list (and build/results/summary.csv).
Anything not measured yet shows as "-".

  python3 scripts/results.py
"""
import csv
import os
import re

from kit_aws import RESULTS, read_jsonl, read_result
from lab_runs import latest_runs

GB = float(1 << 30)


def main():
    rows = []

    def add(section, item, value):
        rows.append((section, item, "-" if value in (None, "") else value))

    st = read_result("lab-status")
    if st:
        for name, f in sorted(st.get("instances", {}).items()):
            add("Lab", f"{name}: az_id / service / sha256", f"{f.get('az_id')} / {f.get('svc')} / {f.get('sha256')}")
        fl = st.get("flow_log", {})
        add("Lab", "flow log status / delivery / aggregation s", f"{fl.get('FlowLogStatus')} / {fl.get('DeliverLogsStatus')} / "
                                                               f"{fl.get('MaxAggregationInterval')}")
    pl = read_result("payloads")
    for name, p in (pl or {}).items():
        add("Lab", f"payload {name}: bytes / sha256", f"{p['bytes']:,} / {p['sha256'][:16]}")

    for r in latest_runs(read_jsonl("runs")):
        main_res = r["results"][-1]
        speed = main_res.get("mbit_s") or main_res.get("calls_per_s") or "-"
        add("Runs", f"{r['run']}: bytes / seconds / Mbit/s or calls/s", f"{r['logical_bytes']:,} / {r['seconds']} / {speed}")
        if r["run"] == "gzip-euw1":
            add("Runs", "gzip-euw1: original -> compressed / ratio / gzip seconds",
                f"{r['original_bytes']:,} -> {r['compressed_bytes']:,} / {r['gzip_ratio']} / {r['gzip_seconds']}")

    fx = read_result("forensics")
    if fx:
        for r in fx["reconciliation"]:
            if r.get("expected_path"):
                add("Forensics", f"{r['run']}: {r['expected_path']} measured / ratio / bytes per packet",
                    f"{r['measured_bytes']:,} / {r['ratio']} / {r['bytes_per_packet']}")
                if "receiver_bytes" in r:
                    add("Forensics", f"{r['run']}: receiver's ENI saw", f"{r['receiver_bytes']:,}")
            add("Forensics", f"{r['run']}: cross-AZ hop bytes / NAT processed bytes",
                f"{r['cross_az_hop_bytes']:,} / {r['nat_processed_bytes']:,}")
        for eni, b in sorted(fx.get("background", {}).items()):
            add("Forensics", f"background (idle run) {eni}: bytes per hour", f"{b['bytes_per_hour']:,}")
        for p in fx["paths_total"][:12]:
            add("Paths (whole build)", f"{p['path']} {p['direction']}", f"{p['bytes']:,}")
        add("Forensics", "IP -> AZ learned from flow logs matches Terraform", not fx["ip_az_mismatches"])
        for q, m in fx["queries"].items():
            add("Athena", f"{q}: rows / bytes scanned / ms", f"{m['rows']} / {m['scanned_bytes']:,} / {m['engine_ms']}")
    nm = read_result("nat-metrics")
    for run, v in ((nm or {}).get("per_run") or {}).items():
        add("NAT CloudWatch", f"{run}: processed CloudWatch / flow logs",
            f"{v['processed']:,} / {v['flowlog_processed'] if v['flowlog_processed'] is not None else '-'}")
    pr = read_result("prices")
    for k, p in ((pr or {}).get("prices") or {}).items():
        add("Prices", f"{k} ({p['usagetype']})", f"US${p['usd']}/{p['unit']}" if "usd" in p else
            " | ".join(f"{t['begin_gb']:.0f}+ GB US${t['usd']}" for t in p["tiers"]))
    cr = read_result("cost-runs")
    if cr:
        for r in cr["rows"]:
            add("Cost per run", f"{r['run']}: total US$ / per GB sent", f"{r['usd_total']:.4f} / "
                f"{r['usd_per_logical_gb']:.4f}" if r["usd_per_logical_gb"] is not None else f"{r['usd_total']:.4f} / -")
        add("Cost per run", "NAT gateway hours estimate / US$", f"{cr['nat_hours_estimate']} / {cr['nat_hours_usd']:.4f}")
    pj = read_result("projection")
    if pj:
        for r in pj["rows"]:
            add("Projection (US$/month)", f"{r['item']}: before / after", f"{r['before_usd']:,.2f} / {r['after_usd']:,.2f}")
        add("Projection (US$/month)", "TOTAL before / after / saving",
            f"{pj['before_usd']:,.2f} / {pj['after_usd']:,.2f} / {pj['before_usd'] - pj['after_usd']:,.2f}")
        add("Projection (US$/month)", "compression ratio used", round(pj["compression_ratio"], 4))
    files = sorted(os.listdir(RESULTS)) if os.path.isdir(RESULTS) else []
    for name in files:
        if name.startswith("ce-") and name.endswith(".json"):
            ce = read_result(name[:-5])
            for g in ce["groups"]:
                if re.search(r"NatGateway|DataTransfer|AWS-Out", g["usage_type"]):
                    add("Cost Explorer", f"{g['day']} {g['usage_type']}: quantity / US$", f"{g['quantity']:.4f} / {g['usd']:.4f}")
    for name in files:
        if name.startswith("tf-") and name.endswith(".txt"):
            line = None
            with open(os.path.join(RESULTS, name), errors="replace") as f:
                for ln in f:
                    if re.search(r"^(Plan:|Destroy complete!|Apply complete!|No changes\.)", ln.strip()):
                        line = ln.strip()
            add("Terraform", name, line)
    if not rows:
        print("nothing measured yet")
        return
    w = max(len(r[1]) for r in rows)
    sec = None
    for s, i, v in rows:
        if s != sec:
            print(f"\n== {s}")
            sec = s
        print(f"  {i:<{w}}  {v}")
    with open(os.path.join(RESULTS, "summary.csv"), "w", newline="") as f:
        csv.writer(f).writerows([("section", "item", "value"), *rows])
    print("\nsaved build/results/summary.csv")


if __name__ == "__main__":
    main()
