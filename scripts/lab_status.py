#!/usr/bin/env python3
"""Is the lab ready? Snapshot the Terraform outputs (build/results/lab.json), check the app service on
every instance through SSM, and check the flow log: status, format, and the files it has delivered
(the Hive-compatible layout). Account IDs are masked in everything printed and saved.

  python3 scripts/lab_status.py               # instances + flow log
  python3 scripts/lab_status.py --flowlogs    # flow log only (also works after the instances are gone)
"""
import sys

from kit_aws import aws, lab_info, mask, write_result
from ssm_run import run as ssm

STATUS_CMD = (
    "T=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60'); "
    "AZ=$(curl -s -H \"X-aws-ec2-metadata-token: $T\" http://169.254.169.254/latest/meta-data/placement/availability-zone-id); "
    "echo name=$(cut -d= -f2 /etc/mvela.conf) svc=$(systemctl is-active mvela-svc) "
    "sha256=$(sha256sum /opt/mvela/mvela_traffic.py | cut -c1-16) az_id=$AZ "
    "cli=$(aws --version 2>&1 | cut -d' ' -f1) py=$(python3 -V 2>&1 | cut -d' ' -f2)"
)


def main():
    flow_only = "--flowlogs" in sys.argv
    info = lab_info(refresh=True)
    acct = aws("sts", "get-caller-identity")["Account"]
    region = info["regions"]["primary"]
    out = {"phases": info["phases"], "instances": {}, "flow_log": {}, "delivered": []}

    if not flow_only:
        if not info["phases"]["traffic_lab"]:
            sys.exit("traffic_lab is false: no instances to check (use --flowlogs)")
        expected = info["app_sha256"][:16]
        ids = {v["id"]: k for k, v in info["lab"].items()}
        res = ssm(list(ids), STATUS_CMD, region, echo=False, timeout=180)
        print(f"== app instances (expected sha256 {expected})")
        ok = 0
        for iid, text in sorted(res.items(), key=lambda kv: ids[kv[0]]):
            name = ids[iid]
            f = dict(x.split("=", 1) for x in text.split() if "=" in x)
            good = f.get("svc") == "active" and f.get("sha256") == expected and f.get("az_id") == info["lab"][name]["az_id"]
            ok += good
            print(f"  {name:<7} {iid}  {info['lab'][name]['private_ip']:<13} az_id={f.get('az_id')} "
                  f"svc={f.get('svc')} sha256={f.get('sha256')} {f.get('cli')} python {f.get('py')}  "
                  f"{'OK' if good else 'CHECK'}")
            out["instances"][name] = f
        print(f"  {ok}/{len(ids)} OK")
        nat = info["nat"]
        print(f"== NAT gateway {nat['id']}: ENI {nat['eni']}, private IP {nat['private_ip']}, az_id {nat['az_id']}")

    fl = aws("ec2", "describe-flow-logs", "--region", region, "--flow-log-ids", info["flow_log_id"])["FlowLogs"][0]
    keep = ("FlowLogStatus", "DeliverLogsStatus", "MaxAggregationInterval", "TrafficType", "LogDestinationType",
            "DestinationOptions", "LogFormat")
    out["flow_log"] = {k: fl.get(k) for k in keep}
    print(f"== flow log {info['flow_log_id']}: status {fl.get('FlowLogStatus')}, delivery {fl.get('DeliverLogsStatus')}, "
          f"aggregation {fl.get('MaxAggregationInterval')} s, {fl.get('TrafficType')}, "
          f"options {fl.get('DestinationOptions')}")
    print(f"   fields: {len(fl.get('LogFormat', '').split())} -> {fl.get('LogFormat')}")
    objs = aws("s3api", "list-objects-v2", "--bucket", info["buckets"]["flowlogs"], "--prefix", "AWSLogs/",
               "--max-items", "1000").get("Contents", [])
    hours = sorted({"/".join(o["Key"].split("/")[4:8]) for o in objs})
    print(f"== delivered files: {len(objs)} (first 1000 listed), hour partitions: {', '.join(hours) or 'none yet'}")
    for o in sorted(objs, key=lambda o: o["Key"])[-3:]:
        k = mask(o["Key"], acct)
        out["delivered"].append({"key": k, "size": o["Size"]})
        print(f"   {k}  ({o['Size']} bytes)")
    if not objs:
        print("   none yet: S3 delivery typically takes about 10 minutes after the first traffic")
    out["delivered_count"] = len(objs)
    out["hour_partitions"] = hours
    write_result("lab-status" + ("-flowlogs" if flow_only else ""), out)
    print("saved build/results/lab-status" + ("-flowlogs" if flow_only else "") + ".json")


if __name__ == "__main__":
    main()
