#!/usr/bin/env python3
"""Generate known, controlled traffic on the lab instances through SSM, one run at a time, and log
exactly when each transfer started and ended (instance clock) in build/results/runs.jsonl.

  python3 scripts/run_traffic.py list                      # the catalogue and what's done
  python3 scripts/run_traffic.py prepare                   # build the CSV payloads on app-a / app-b
  python3 scripts/run_traffic.py run <name> [<name> ...]   # in order, with a quiet gap before each

Before every run the script waits until QUIET_GAP_S seconds have passed since the previous run
ended, so each run gets its own clean window in the flow logs.
"""
import json
import sys
import time

from kit_aws import RESULTS, append_jsonl, lab_info, read_jsonl, result_lines, write_result
from lab_runs import (DOWNLOAD_URLS, PAYLOAD_A, PAYLOADS, QUIET_GAP_S, RUNS, TOOL, latest_runs)
from ssm_run import run as ssm


def command_for(name, spec, info):
    lab, buckets, regions = info["lab"], info["buckets"], info["regions"]
    src = spec["src"]
    if spec["kind"] == "idle":
        return f"{TOOL} idle --seconds 240"
    if spec["kind"] == "s3":
        f = PAYLOADS[src][0]
        region = regions["second"] if spec["bucket"] == "replica" else regions["primary"]
        return (f"{TOOL} s3-put --file {f} --bucket {buckets[spec['bucket']]} --key runs/{name}/payload.csv "
                f"--region {region} --deadline {spec['timeout'] - 60}")
    if spec["kind"] == "gzip-s3":
        return (f"rm -f {PAYLOAD_A}.gz && {TOOL} gzip --in {PAYLOAD_A} --out {PAYLOAD_A}.gz && "
                f"{TOOL} s3-put --file {PAYLOAD_A}.gz --bucket {buckets['replica']} --key runs/{name}/payload.csv.gz "
                f"--region {regions['second']} --deadline 600")
    if spec["kind"] == "tcp":
        return f"{TOOL} tcp-send --host {lab[spec['peer']]['private_ip']} --bytes {spec['logical']} --deadline 600"
    if spec["kind"] == "chatty":
        return (f"{TOOL} chatty --host {lab[spec['peer']]['private_ip']} --calls 32768 --req-bytes 4096 "
                f"--resp-bytes 1024 --workers 8 --deadline 600")
    if spec["kind"] == "download":
        urls = " ".join(f"--url '{u}'" for u in DOWNLOAD_URLS)
        return f"{TOOL} download --bytes {spec['logical']} {urls} --deadline 600"
    raise ValueError(spec["kind"])


def quiet_gap():
    done = [r.get("local_done", 0) for r in read_jsonl("runs")]
    if not done:
        return
    wait = QUIET_GAP_S - (time.time() - max(done))
    while wait > 0:
        print(f"  quiet gap: {wait:.0f} s before the next run (keeps flow-log windows apart)", flush=True)
        time.sleep(min(30, wait))
        wait = QUIET_GAP_S - (time.time() - max(done))


def do_run(name, info):
    spec = RUNS[name]
    if not info["phases"]["traffic_lab"]:
        sys.exit("traffic_lab is false: the instances and the NAT gateway are gone")
    if spec["endpoint"] is not None and bool(info["s3_gateway_endpoint_id"]) != spec["endpoint"]:
        sys.exit(f"{name} needs the S3 gateway endpoint {'ON' if spec['endpoint'] else 'OFF'} "
                 f"(it is {'ON' if info['s3_gateway_endpoint_id'] else 'OFF'}): set s3_gateway_endpoint in infra/phases.auto.tfvars and apply first")
    quiet_gap()
    src = info["lab"][spec["src"]]
    cmd = command_for(name, spec, info)
    print(f"\n== {name}: {spec['what']}\n   on {spec['src']} ({src['id']}): {cmd[:150]}", flush=True)
    out = ssm([src["id"]], cmd, info["regions"]["primary"], echo=False, timeout=spec["timeout"])[src["id"]]
    res = result_lines(out)
    if not res:
        sys.exit(f"{name}: no RESULT line in the output:\n{out[-2000:]}")
    main = res[-1]  # for gzip-s3 the last line is the upload
    rec = {
        "run": name, "kind": spec["kind"], "src": spec["src"], "src_ip": src["private_ip"],
        "peer": spec.get("peer") or spec.get("bucket") or ("internet" if spec["kind"] == "download" else None),
        "logical_bytes": main["bytes"], "t0": main["t0"], "t1": main["t1"], "seconds": main["seconds"],
        "expect": spec["expect"], "endpoint_on": bool(info["s3_gateway_endpoint_id"]),
        "results": res, "local_done": round(time.time(), 3),
    }
    if spec["kind"] == "gzip-s3":
        g = res[0]
        rec.update(original_bytes=g["in_bytes"], compressed_bytes=g["out_bytes"], gzip_ratio=g["ratio"],
                   gzip_seconds=g["seconds"])
    append_jsonl("runs", rec)
    extra = f"  ({main.get('mbit_s', main.get('calls_per_s', ''))} {'Mbit/s' if 'mbit_s' in main else 'calls/s'})" \
        if spec["kind"] != "idle" else ""
    print(f"   done: {rec['logical_bytes']:,} bytes in {rec['seconds']} s{extra}")
    if spec["kind"] == "gzip-s3":
        print(f"   gzip: {rec['original_bytes']:,} -> {rec['compressed_bytes']:,} bytes "
              f"(ratio {rec['gzip_ratio']}, {rec['gzip_seconds']} s of CPU on the instance)")
    print("   logged to build/results/runs.jsonl")


def prepare(info):
    if not info["phases"]["traffic_lab"]:
        sys.exit("traffic_lab is false: the instances are gone")
    out = {}
    for name, (path, size) in PAYLOADS.items():
        iid = info["lab"][name]["id"]
        print(f"== {name}: building {size:,} bytes of shipment-events CSV at {path}", flush=True)
        o = ssm([iid], f"{TOOL} make-payload --bytes {size} --out {path}", info["regions"]["primary"],
                echo=False, timeout=600)[iid]
        r = result_lines(o)[-1]
        print(f"   {r['bytes']:,} bytes, sha256 {r['sha256'][:16]}..., {r['seconds']} s")
        out[name] = r
    print("payloads ready (the generator is deterministic: same seed -> same sha256 every build)")
    write_result("payloads", out)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "prepare", "run"):
        sys.exit(__doc__)
    if sys.argv[1] == "list":
        done = {r["run"]: r for r in latest_runs(read_jsonl("runs"))}
        for name, s in sorted(RUNS.items(), key=lambda kv: kv[1]["order"]):
            d = done.get(name)
            mark = f"done {d['logical_bytes']:,} B" if d else "-"
            ep = {True: "endpoint ON", False: "endpoint OFF", None: ""}[s["endpoint"]]
            print(f"  {s['order']:>2} {name:<14} {mark:<22} {ep:<13} {s['what']}")
        return
    info = lab_info(refresh=True)
    if sys.argv[1] == "prepare":
        prepare(info)
        return
    names = sys.argv[2:]
    bad = [n for n in names if n not in RUNS]
    if not names or bad:
        sys.exit(f"unknown run(s) {bad}; choose from: {', '.join(RUNS)}")
    for n in names:
        do_run(n, info)
    print(f"\nruns so far: {len(latest_runs(read_jsonl('runs')))} (python3 scripts/run_traffic.py list)  [{RESULTS}]")


if __name__ == "__main__":
    main()
