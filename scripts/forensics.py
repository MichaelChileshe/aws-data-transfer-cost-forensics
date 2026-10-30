#!/usr/bin/env python3
"""Data-transfer forensics: run the saved Athena queries (sql/) over the VPC flow logs, attribute
every byte to a path (same-AZ, cross-AZ, S3 via NAT, S3 via gateway endpoint, inter-Region,
internet), and reconcile what the flow logs measured with what each run is known to have sent.

  python3 scripts/forensics.py check    # have the flow logs arrived? (hour partitions, last record)
  python3 scripts/forensics.py all      # every query + attribution + reconciliation -> forensics.json

Peers outside the VPC are named with AWS's published ip-ranges.json (service + Region), so an S3
address in eu-west-1 is told apart from one in us-east-1. Filled-in SQL lands in build/results/sql/.
"""
import ipaddress
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from kit_aws import RESULTS, ROOT, aws, lab_info, read_jsonl, write_result
from lab_runs import RUNS, WINDOW_PAD_S, latest_runs

SQL_DIR = os.path.join(ROOT, "sql")
IP_RANGES_URL = "https://ip-ranges.amazonaws.com/ip-ranges.json"
QUERY_DEADLINE_S = 180
QUERIES = ["01_top_talkers", "02_paths_by_run", "03_cross_az_hops", "04_nat_legs", "05_ip_az_map"]


def utc(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------- rendering

def partitions(t0, t1):
    """Partition predicate covering every UTC hour from t0 to t1 (one group per day)."""
    start = datetime.fromtimestamp(t0, timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = datetime.fromtimestamp(t1, timezone.utc)
    days = {}
    h = start
    while h <= end:
        days.setdefault((h.year, h.month, h.day), []).append(h.hour)
        h += timedelta(hours=1)
    parts = [f"(\"year\" = '{y:04d}' AND \"month\" = '{m:02d}' AND \"day\" = '{d:02d}' "
             f"AND \"hour\" BETWEEN '{min(hs):02d}' AND '{max(hs):02d}')" for (y, m, d), hs in sorted(days.items())]
    return "(" + " OR ".join(parts) + ")"


def window(runs):
    """The analysis window: from 10 minutes before the first run to 15 minutes after the last."""
    if runs:
        return int(min(r["t0"] for r in runs)) - 600, int(max(r["t1"] for r in runs)) + 900
    now = int(time.time())
    return now - 3 * 3600, now


def render(name, info, runs, t0, t1):
    nat = info.get("nat") or {}
    vals = ", ".join(f"('{r['run']}', {int(r['t0'])}, {int(r['t1']) + 1})" for r in runs) or "('(none)', 0, 0)"
    with open(os.path.join(SQL_DIR, "_base.sql")) as f:
        base = "\n".join(l for l in f.read().splitlines() if not l.startswith("--"))
    with open(os.path.join(SQL_DIR, f"{name}.sql")) as f:
        sql = f.read()
    sql = sql.replace("{{BASE}}", base.strip())
    prefix = info["vpc"]["cidr"].split(".")[0] + "." + info["vpc"]["cidr"].split(".")[1] + "."
    subs = {"TABLE": f"{info['athena']['database']}.{info['athena']['table']}", "PARTITIONS": partitions(t0, t1),
            "VPC_ID": info["vpc"]["id"], "T0": str(t0), "T1": str(t1), "RUNS": vals, "PAD": str(WINDOW_PAD_S),
            "VPC_PREFIX": prefix, "NAT_ENI": nat.get("eni", "-"), "NAT_IP": nat.get("private_ip", "-")}
    for k, v in subs.items():
        sql = sql.replace("{{" + k + "}}", v)
    if "{{" in sql:
        sys.exit(f"{name}: unfilled placeholder in the SQL")
    os.makedirs(os.path.join(RESULTS, "sql"), exist_ok=True)
    with open(os.path.join(RESULTS, "sql", f"{name}.sql"), "w") as f:
        f.write(sql + "\n")
    return sql


# ---------------------------------------------------------------- Athena

def athena(name, sql, info):
    wg, db = info["athena"]["workgroup"], info["athena"]["database"]
    qid = aws("athena", "start-query-execution", "--work-group", wg, "--query-execution-context",
              f"Database={db}", "--query-string", sql)["QueryExecutionId"]
    t0, last = time.time(), 0.0
    while True:
        ex = aws("athena", "get-query-execution", "--query-execution-id", qid)["QueryExecution"]
        state = ex["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            sys.exit(f"{name}: Athena {state}: {ex['Status'].get('StateChangeReason', '')}\n"
                     f"(the SQL that ran is in build/results/sql/{name}.sql)")
        if time.time() - t0 > QUERY_DEADLINE_S:
            aws("athena", "stop-query-execution", "--query-execution-id", qid)
            sys.exit(f"{name}: still {state} after {QUERY_DEADLINE_S} s - stopped it")
        if time.time() - last > 10:
            print(f"  {name}: {state} ...", flush=True)
            last = time.time()
        time.sleep(2)
    stats = ex.get("Statistics", {})
    rows = aws("athena", "get-query-results", "--query-execution-id", qid)["ResultSet"]["Rows"]
    header = [c.get("VarCharValue") for c in rows[0]["Data"]] if rows else []
    data = [dict(zip(header, [c.get("VarCharValue") for c in r["Data"]])) for r in rows[1:]]
    meta = {"query_id": qid, "scanned_bytes": int(stats.get("DataScannedInBytes", 0)),
            "engine_ms": int(stats.get("EngineExecutionTimeInMillis", 0)), "rows": len(data)}
    write_result(f"athena-{name}", {"meta": meta, "rows": data})
    print(f"  {name}: {len(data)} rows, scanned {meta['scanned_bytes']:,} bytes, {meta['engine_ms']} ms")
    return data, meta


def num(x):
    return int(float(x)) if x not in (None, "", "-") else 0


# ---------------------------------------------------------------- naming

class IpRanges:
    """Longest-prefix lookup in AWS's ip-ranges.json; a specific service beats the AMAZON superset."""

    def __init__(self):
        path = os.environ.get("MVELA_IP_RANGES") or os.path.join(ROOT, "build", "cache", "ip-ranges.json")
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            print(f"  downloading {IP_RANGES_URL}")
            with urllib.request.urlopen(IP_RANGES_URL, timeout=30) as r, open(path, "wb") as f:
                f.write(r.read())
        with open(path) as f:
            d = json.load(f)
        self.meta = {"syncToken": d.get("syncToken"), "createDate": d.get("createDate")}
        self.nets = [(ipaddress.ip_network(p["ip_prefix"]), p["region"], p["service"]) for p in d["prefixes"]]

    def lookup(self, ip):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return None
        best = None
        for net, region, service in self.nets:
            if a in net:
                key = (net.prefixlen, service != "AMAZON")
                if best is None or key > best[0]:
                    best = (key, region, service)
        return (best[1], best[2]) if best else None


def build_names(info):
    names = {v["private_ip"]: k for k, v in (info.get("lab") or {}).items()}
    enis = {v["eni"]: k for k, v in (info.get("lab") or {}).items()}
    if info.get("nat"):
        names[info["nat"]["private_ip"]] = "nat-gw"
        enis[info["nat"]["eni"]] = "nat-gw"
    return names, enis


def label(row, ipr, cache):
    """Path label for one 02_paths_by_run row."""
    route = row["route"]
    if route in ("same-AZ", "cross-AZ") or route.startswith("in-VPC"):
        return route
    peer = row["peer"]
    if peer not in cache:
        cache[peer] = ipr.lookup(peer)
    hit = cache[peer]
    svc = row["peer_service"] if row["peer_service"] not in (None, "", "-") else (hit[1] if hit else None)
    if not svc:
        return f"internet {route}"
    region = hit[0] if hit else "?"
    return f"{svc} {region} {route}"


# ---------------------------------------------------------------- analysis

def analyse(info, runs, results, ipr):
    names, enis = build_names(info)
    cache = {}
    paths = {}
    for r in results["02_paths_by_run"]:
        key = (r["run"], enis.get(r["interface_id"], r["interface_id"]), r["flow_direction"], label(r, ipr, cache),
               names.get(r["peer"], r["peer"]) if r["route"] in ("same-AZ", "cross-AZ") else "")
        p = paths.setdefault(key, {"bytes": 0, "packets": 0, "records": 0})
        p["bytes"] += num(r["bytes"])
        p["packets"] += num(r["packets"])
        p["records"] += num(r["records"])
    rows = [dict(run=k[0], eni=k[1], direction=k[2], path=k[3], peer=k[4], **v) for k, v in paths.items()]
    totals = {}
    for r in rows:
        t = totals.setdefault((r["path"], r["direction"]), 0)
        totals[(r["path"], r["direction"])] = t + r["bytes"]
    hops = [dict(run=h["run"], src=names.get(h["hop_src"], h["hop_src"]), dst=names.get(h["hop_dst"], h["hop_dst"]),
                 from_az=h["from_az"], to_az=h["to_az"], kind=h["kind"], bytes=num(h["bytes"]),
                 packets=num(h["packets"])) for h in results["03_cross_az_hops"]]
    nat = {n["run"]: {k: num(n[k]) for k in ("in_from_source", "out_to_destination", "in_from_destination",
                                               "out_to_source", "bytes", "records")} for n in results["04_nat_legs"]}
    for v in nat.values():
        v["processed"] = v["in_from_source"] + v["in_from_destination"]
    ip_az = {r["ip"]: r["az_id"] for r in results["05_ip_az_map"]}
    tf_az = {v["private_ip"]: v["az_id"] for v in (info.get("lab") or {}).values()}
    if info.get("nat"):
        tf_az[info["nat"]["private_ip"]] = info["nat"]["az_id"]
    mism = {ip: (ip_az.get(ip), az) for ip, az in tf_az.items() if ip in ip_az and ip_az[ip] != az}

    recon = []
    for run in runs:
        spec = RUNS.get(run["run"], {})
        exp = run.get("expect") or spec.get("expect")
        mine = [r for r in rows if r["run"] == run["run"]]
        cross = sum(h["bytes"] for h in hops if h["run"] == run["run"] and h["kind"] == "cross-AZ")
        natp = nat.get(run["run"], {}).get("processed", 0)
        rec = {"run": run["run"], "src": run["src"], "logical_bytes": run["logical_bytes"],
               "seconds": run["seconds"], "cross_az_hop_bytes": cross, "nat_processed_bytes": natp}
        if exp:
            d, path = exp
            on = [r for r in mine if r["eni"] == run["src"] and r["path"] == path]
            eg = sum(r["bytes"] for r in on if r["direction"] == "egress")
            ing = sum(r["bytes"] for r in on if r["direction"] == "ingress")
            main = {"egress": eg, "ingress": ing, "both": eg + ing}[d]
            pk = sum(r["packets"] for r in on if d == "both" or r["direction"] == d)
            rec.update(expected_path=path, direction=d, measured_bytes=main,
                       reverse_bytes={"egress": ing, "ingress": eg, "both": 0}[d],
                       ratio=round(main / run["logical_bytes"], 4) if run["logical_bytes"] else None,
                       bytes_per_packet=round(main / pk) if pk else None,
                       found=main > 0)
            if path in ("same-AZ", "cross-AZ") and run.get("peer") in names.values():
                rec["receiver_bytes"] = sum(r["bytes"] for r in mine if r["eni"] == run["peer"] and r["path"] == path
                                            and r["direction"] == "ingress")
        rec["other_paths"] = sorted(({"eni": r["eni"], "direction": r["direction"], "path": r["path"],
                                      "bytes": r["bytes"]} for r in mine
                                     if not (exp and r["eni"] == run["src"] and r["path"] == exp[1])),
                                    key=lambda x: -x["bytes"])[:6]
        recon.append(rec)

    background = {}
    idle = next((r for r in runs if r["run"] == "idle"), None)
    if idle:
        hours = max(idle["t1"] - idle["t0"], 1) / 3600
        for r in rows:
            if r["run"] == "idle":
                b = background.setdefault(r["eni"], {"bytes": 0, "by_path": {}})
                b["bytes"] += r["bytes"]
                b["by_path"][r["path"]] = b["by_path"].get(r["path"], 0) + r["bytes"]
        for b in background.values():
            b["bytes_per_hour"] = round(b["bytes"] / hours)
    return {"paths_by_run": rows, "paths_total": [{"path": k[0], "direction": k[1], "bytes": v}
                                                  for k, v in sorted(totals.items(), key=lambda kv: -kv[1])],
            "hops": hops, "nat_legs": nat, "ip_az": ip_az, "ip_az_mismatches": mism,
            "reconciliation": recon, "background": background}


def show(an, runs):
    print("\n== Reconciliation: what each run sent vs what the flow logs measured on the sender's ENI")
    print(f"  {'run':<14} {'expected path':<32} {'generated':>15} {'measured':>15} {'ratio':>7} {'B/pkt':>6} "
          f"{'cross-AZ hops':>15} {'NAT processed':>15}")
    for r in an["reconciliation"]:
        print(f"  {r['run']:<14} {r.get('expected_path', '(background)'):<32} {r['logical_bytes']:>15,} "
              f"{r.get('measured_bytes', 0):>15,} {str(r.get('ratio', '-')):>7} {str(r.get('bytes_per_packet', '-')):>6} "
              f"{r['cross_az_hop_bytes']:>15,} {r['nat_processed_bytes']:>15,}"
              + ("" if r.get("found", True) else "   <- expected path NOT found"))
        if "receiver_bytes" in r:
            print(f"  {'':<14} receiver's ENI saw {r['receiver_bytes']:,} bytes arrive on the same path")
    print("\n== Bytes by path over the whole build (instance ENIs)")
    for p in an["paths_total"][:20]:
        print(f"  {p['path']:<42} {p['direction']:<8} {p['bytes']:>15,}")
    if an["background"]:
        print("\n== Background during the idle run (per instance, bytes per hour)")
        for eni, b in sorted(an["background"].items()):
            print(f"  {eni:<8} {b['bytes_per_hour']:>12,} B/h  " + ", ".join(f"{k} {v:,}" for k, v in b["by_path"].items()))
    print("\n== NAT gateway ENI legs per run (bytes)")
    for run, v in sorted(an["nat_legs"].items()):
        print(f"  {run:<16} from source {v['in_from_source']:>14,}  to dest {v['out_to_destination']:>14,}  "
              f"from dest {v['in_from_destination']:>14,}  to source {v['out_to_source']:>14,}  processed {v['processed']:>14,}")
    print("\n== IP -> AZ learned from the flow logs: " +
          ("matches Terraform" if not an["ip_az_mismatches"] else f"MISMATCH {an['ip_az_mismatches']}"))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("check", "all"):
        sys.exit(__doc__)
    info = lab_info()
    runs = latest_runs(read_jsonl("runs"))
    t0, t1 = window(runs)
    print(f"window {utc(t0)} -> {utc(t1)}, {len(runs)} run(s)")
    if sys.argv[1] == "check":
        data, meta = athena("00_layout_check", render("00_layout_check", info, runs, t0, t1), info)
        for r in data:
            print(f"  {r['year']}-{r['month']}-{r['day']} hour {r['hour']}: {num(r['records']):,} records, "
                  f"{r['enis']} ENIs, last record ends {utc(num(r['last_end']))}")
        if data:
            print(f"  a file Athena read: .../{'/'.join(data[-1]['sample_file'].split('/')[-6:])}")
        last_end = max((num(r["last_end"]) for r in data), default=0)
        if runs:
            need = max(r["t1"] for r in runs)
            print(f"flow logs cover the last run ({runs[-1]['run']}, ended {utc(need)}): "
                  f"{'YES' if last_end >= need else 'NOT YET - wait 5 minutes and check again'}")
        write_result("forensics-check", {"meta": meta, "rows": data, "last_end": last_end})
        return
    results, metas = {}, {}
    for q in QUERIES:
        results[q], metas[q] = athena(q, render(q, info, runs, t0, t1), info)
    ipr = IpRanges()
    an = analyse(info, runs, results, ipr)
    an.update(window={"t0": t0, "t1": t1, "t0_utc": utc(t0), "t1_utc": utc(t1)}, queries=metas,
              ip_ranges=ipr.meta, top_talkers=results["01_top_talkers"][:15])
    show(an, runs)
    total_scan = sum(m["scanned_bytes"] for m in metas.values())
    print(f"\nAthena scanned {total_scan:,} bytes for {len(metas)} queries "
          f"(Athena bills per TB scanned, rounded up to 10 MB per query)")
    write_result("forensics", an)
    print("saved build/results/forensics.json and athena-*.json; the SQL that ran: build/results/sql/")


if __name__ == "__main__":
    main()
