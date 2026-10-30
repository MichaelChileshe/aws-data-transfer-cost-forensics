#!/usr/bin/env python3
"""Turn measured bytes into money, then project Mvelaphanda's monthly bill before and after the fixes.
Prices come ONLY from build/results/prices.json (scripts/prices.py, Price List API); if a price the
model needs is missing, it stops instead of guessing.

  python3 scripts/cost_model.py measured   # each lab run's bytes, priced per path -> cost-runs.csv
  python3 scripts/cost_model.py project    # profile/mvelaphanda-traffic.json -> projection.csv
  python3 scripts/cost_model.py            # both

Billing rules used (1 GB = 2^30 bytes):
  NAT gateway       per hour + per GB processed (both directions: from instances + from destinations)
  cross-AZ          per GB in EACH direction: a byte that crosses is billed out on one side and in on
                    the other, so 2 x the intra-Region rate per GB crossing (cross-AZ hops from Athena)
  same AZ, private  free;  S3 in the same Region  free (also through the NAT: only NAT processing)
  inter-Region      per GB out of the source Region (us-east-1 -> eu-west-1, and S3's answers back)
  internet out      tiered per GB after the free monthly allowance;  internet in  per the price list
  S3 gateway endpoint  no charge
"""
import csv
import json
import math
import os
import sys

from kit_aws import RESULTS, ROOT, read_jsonl, read_result, write_result
from lab_runs import latest_runs

GB = float(1 << 30)
REQUIRED = ["nat_hour", "nat_gb", "intra_region_gb", "use1_to_euw1_gb", "euw1_to_use1_gb", "internet_out",
            "internet_in"]


class Prices:
    def __init__(self, extra=()):
        d = read_result("prices")
        if not d:
            sys.exit("build/results/prices.json is missing: run python3 scripts/prices.py first")
        if d.get("errors"):
            sys.exit("prices.json has errors (missing or ambiguous prices):\n  " + "\n  ".join(d["errors"]))
        self.p, self.doc = d["prices"], d["documented"]
        missing = [k for k in list(REQUIRED) + list(extra) if k not in self.p]
        if missing:
            sys.exit(f"prices missing: {missing} - the cost model stops rather than guess (run scripts/prices.py)")

    def rate(self, key):
        p = self.p[key]
        if "usd" in p:
            return p["usd"]
        return p["tiers"][0]["usd"]

    def first_paid(self, key):
        p = self.p[key]
        return p["usd"] if "usd" in p else next((t["usd"] for t in p["tiers"] if t["usd"] > 0), 0.0)

    def tiered(self, key, gb, free_gb=0.0):
        """Monthly cost of gb at a tiered price. The free allowance is only applied if the price list
        doesn't already start with a $0 tier (no double counting)."""
        p = self.p[key]
        if "usd" in p:
            return max(gb - free_gb, 0) * p["usd"]
        tiers = p["tiers"]
        if tiers[0]["usd"] == 0:
            free_gb = 0.0
        left, cost = max(gb - free_gb, 0.0), 0.0
        for t in tiers:
            size = math.inf if t["end_gb"] is None else t["end_gb"] - t["begin_gb"]
            use = min(left, size)
            cost += use * t["usd"]
            left -= use
            if left <= 0:
                break
        return cost


def write_csv(name, rows, cols):
    with open(os.path.join(RESULTS, f"{name}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- measured

def measured(pr):
    fx = read_result("forensics")
    if not fx:
        sys.exit("build/results/forensics.json is missing: run python3 scripts/forensics.py all first")
    runs = latest_runs(read_jsonl("runs"))
    rows = []
    nat_gb, intra, out_eu, back_eu = pr.rate("nat_gb"), pr.rate("intra_region_gb"), pr.rate("use1_to_euw1_gb"), \
        pr.rate("euw1_to_use1_gb")
    inet = pr.first_paid("internet_out")
    for rec in fx["reconciliation"]:
        name = rec["run"]
        mine = [p for p in fx["paths_by_run"] if p["run"] == name]
        eu_out = sum(p["bytes"] for p in mine if "eu-west-1" in p["path"] and p["direction"] == "egress")
        eu_back = sum(p["bytes"] for p in mine if "eu-west-1" in p["path"] and p["direction"] == "ingress")
        net_out = sum(p["bytes"] for p in mine if p["path"].startswith("internet") and p["direction"] == "egress")
        r = {"run": name, "logical_bytes": rec["logical_bytes"], "nat_processed_bytes": rec["nat_processed_bytes"],
             "cross_az_hop_bytes": rec["cross_az_hop_bytes"], "inter_region_out_bytes": eu_out,
             "inter_region_back_bytes": eu_back, "internet_out_bytes": net_out}
        r["usd_nat"] = rec["nat_processed_bytes"] / GB * nat_gb
        r["usd_cross_az"] = rec["cross_az_hop_bytes"] / GB * intra * 2
        r["usd_inter_region"] = eu_out / GB * out_eu + eu_back / GB * back_eu
        r["usd_internet_out"] = net_out / GB * inet
        r["usd_total"] = r["usd_nat"] + r["usd_cross_az"] + r["usd_inter_region"] + r["usd_internet_out"]
        r["usd_per_logical_gb"] = (r["usd_total"] / (rec["logical_bytes"] / GB)) if rec["logical_bytes"] else None
        rows.append(r)
    hours = math.ceil((max(r["t1"] for r in runs) - min(r["t0"] for r in runs)) / 3600) + 1 if runs else 0
    nat_hours_usd = hours * pr.rate("nat_hour")
    print("== Measured: what each run's bytes cost (list prices, per path)")
    print(f"  {'run':<15} {'NAT':>9} {'cross-AZ':>9} {'inter-Reg':>9} {'inet out':>9} {'total':>9} {'per GB sent':>12}")
    for r in rows:
        per = f"{r['usd_per_logical_gb']:.4f}" if r["usd_per_logical_gb"] is not None else "-"
        print(f"  {r['run']:<15} {r['usd_nat']:>9.4f} {r['usd_cross_az']:>9.4f} {r['usd_inter_region']:>9.4f} "
              f"{r['usd_internet_out']:>9.4f} {r['usd_total']:>9.4f} {per:>12}")
    total = sum(r["usd_total"] for r in rows)
    print(f"  data charges for every run: US${total:.4f};  NAT gateway hours (estimate, {hours} h incl. "
          f"partial hours): US${nat_hours_usd:.4f}")
    print("  internet out is priced at the first paid tier; a lab this size sits inside the free 100 GB/month")
    cols = list(rows[0].keys()) if rows else ["run"]
    write_csv("cost-runs", rows, cols)
    write_result("cost-runs", {"rows": rows, "nat_hours_estimate": hours, "nat_hours_usd": nat_hours_usd,
                               "data_usd_total": total})
    print("saved build/results/cost-runs.csv and cost-runs.json")


# ---------------------------------------------------------------- projection

def projection(pr):
    with open(os.path.join(ROOT, "profile", "mvelaphanda-traffic.json")) as f:
        prof = json.load(f)
    fx, tb = prof["fixes"], prof["traffic_tb_month"]
    pr_cf = Prices(extra=[fx["cloudfront_price_key"]] if fx.get("cloudfront_for_egress") else [])
    ratio = fx["compression_ratio"]
    if ratio == "measured":
        g = next((r for r in latest_runs(read_jsonl("runs")) if r["run"] == "gzip-euw1"), None)
        if not g:
            sys.exit("compression_ratio is 'measured' but the gzip-euw1 run hasn't happened yet")
        ratio = g["compressed_bytes"] / g["original_bytes"]
    shrink = 1 - fx["compressible_share"] + fx["compressible_share"] * ratio
    bg = (read_result("forensics") or {}).get("background", {})
    bg_bph = sum(v["bytes_per_hour"] for k, v in bg.items() if k.startswith("app")) / max(
        len([k for k in bg if k.startswith("app")]), 1)
    bg_tb = bg_bph * prof["instances"] * prof["month_hours"] / GB / 1024
    hrs, intra2 = prof["month_hours"], pr.rate("intra_region_gb") * 2
    T = 1024.0

    nat_before_tb = tb["s3_same_region"] + tb["replication_to_eu"] + tb["internet_ingress"] + bg_tb
    nat_after_tb = (0 if fx["s3_gateway_endpoint"] else tb["s3_same_region"]) + \
        (0 if fx["replication_via_s3_crr"] else tb["replication_to_eu"] * shrink) + tb["internet_ingress"] + bg_tb
    repl_after = tb["replication_to_eu"] * (shrink if "replication_to_eu" in fx["compress"] else 1)
    egress_after = tb["internet_egress"] * (shrink if "internet_egress" in fx["compress"] else 1)
    nats_after = prof["azs"] if fx["nat_per_az"] else prof["nat_gateways_before"]
    xaz_before = tb["service_calls"] * prof["shares_before"]["service_calls_cross_az"]
    xaz_after = tb["service_calls"] * fx["az_affinity_cross_az_share"]
    nat_xaz_before = nat_before_tb * prof["shares_before"]["nat_traffic_from_other_az"]
    nat_xaz_after = 0 if fx["nat_per_az"] else nat_after_tb * prof["shares_before"]["nat_traffic_from_other_az"]
    dto_after = pr.tiered("internet_out", egress_after * T, pr.doc["internet_out_free_gb_month"])
    cf_after = pr_cf.tiered(fx["cloudfront_price_key"], egress_after * T, pr.doc["cloudfront_free_gb_month"]) \
        if fx.get("cloudfront_for_egress") else None

    rows = [
        ("NAT gateway hours", "-", prof["nat_gateways_before"] * hrs * pr.rate("nat_hour"),
         "-", nats_after * hrs * pr.rate("nat_hour"), "one NAT gateway per AZ" if fx["nat_per_az"] else "-"),
        ("NAT processing (S3 + replication + inbound + background)", nat_before_tb,
         nat_before_tb * T * pr.rate("nat_gb"), nat_after_tb, nat_after_tb * T * pr.rate("nat_gb"),
         "S3 gateway endpoint; replication by S3 CRR (bypasses the NAT)"),
        ("cross-AZ hop to the NAT gateway", nat_xaz_before, nat_xaz_before * T * intra2, nat_xaz_after,
         nat_xaz_after * T * intra2, "NAT gateway in every AZ"),
        ("service calls crossing AZs", xaz_before, xaz_before * T * intra2, xaz_after, xaz_after * T * intra2,
         f"AZ affinity (cross-AZ share {prof['shares_before']['service_calls_cross_az']} -> "
         f"{fx['az_affinity_cross_az_share']})"),
        ("S3 same Region transfer", tb["s3_same_region"], 0.0, tb["s3_same_region"], 0.0, "always free"),
        ("inter-Region us-east-1 -> eu-west-1", tb["replication_to_eu"],
         tb["replication_to_eu"] * T * pr.rate("use1_to_euw1_gb"), repl_after,
         repl_after * T * pr.rate("use1_to_euw1_gb"), f"compression (x{shrink:.3f})"),
        ("internet egress", tb["internet_egress"],
         pr.tiered("internet_out", tb["internet_egress"] * T, pr.doc["internet_out_free_gb_month"]), egress_after,
         cf_after if cf_after is not None else dto_after,
         ("compression + CloudFront" if cf_after is not None else "compression")),
        ("internet ingress", tb["internet_ingress"], tb["internet_ingress"] * T * pr.rate("internet_in"),
         tb["internet_ingress"], tb["internet_ingress"] * T * pr.rate("internet_in"), "-"),
    ]
    out = [{"item": r[0], "before_tb": r[1] if r[1] == "-" else round(r[1], 3), "before_usd": round(r[2], 2),
            "after_tb": r[3] if r[3] == "-" else round(r[3], 3), "after_usd": round(r[4], 2),
            "saving_usd": round(r[2] - r[4], 2), "fix": r[5]} for r in rows]
    before, after = sum(r["before_usd"] for r in out), sum(r["after_usd"] for r in out)
    print("== Projection: Mvelaphanda's monthly data-transfer bill (declared profile, list prices)")
    print(f"  compression ratio used: {ratio:.4f} ({'measured in the lab' if fx['compression_ratio'] == 'measured' else 'declared'}),"
          f" compressible share {fx['compressible_share']} -> bytes x{shrink:.3f}")
    print(f"  background through the NAT (measured idle run): {bg_bph:,.0f} B/h per instance -> {bg_tb:.3f} TB/month "
          f"for {prof['instances']} instances")
    print(f"  {'item':<58} {'before TB':>10} {'before US$':>11} {'after TB':>9} {'after US$':>10}  fix")
    for r in out:
        print(f"  {r['item']:<58} {str(r['before_tb']):>10} {r['before_usd']:>11,.2f} {str(r['after_tb']):>9} "
              f"{r['after_usd']:>10,.2f}  {r['fix']}")
    print(f"  {'TOTAL':<58} {'':>10} {before:>11,.2f} {'':>9} {after:>10,.2f}  saving US${before - after:,.2f} "
          f"({(before - after) / before * 100 if before else 0:.1f}%)")
    print(f"  EC2 compute (declared): US${prof['ec2_compute_usd_month']:,.2f} -> data transfer before the fixes is "
          f"{before / prof['ec2_compute_usd_month']:.2f} x the EC2 compute bill")
    if cf_after is not None:
        better = "cheaper" if cf_after < dto_after else "MORE EXPENSIVE"
        print(f"  egress check: after compression, CloudFront ({pr.p[fx['cloudfront_price_key']]['location']}) "
              f"US${cf_after:,.2f} vs straight from us-east-1 US${dto_after:,.2f} -> CloudFront is {better} per GB here;"
              f" its case rests on caching and edge latency, not only on the per-GB price")
    write_csv("projection", out, ["item", "before_tb", "before_usd", "after_tb", "after_usd", "saving_usd", "fix"])
    write_result("projection", {"profile": prof, "compression_ratio": ratio, "shrink": shrink,
                                "background_bytes_per_instance_hour": bg_bph, "rows": out, "before_usd": before,
                                "after_usd": after, "egress_dto_after_usd": dto_after, "egress_cloudfront_after_usd": cf_after})
    print("saved build/results/projection.csv and projection.json")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "both"
    if what not in ("measured", "project", "both"):
        sys.exit(__doc__)
    pr = Prices()
    if what in ("measured", "both"):
        measured(pr)
    if what in ("project", "both"):
        print()
        projection(pr)


if __name__ == "__main__":
    main()
