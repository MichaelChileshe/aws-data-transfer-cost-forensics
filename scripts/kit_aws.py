"""Shared helpers for the repo's scripts: call the AWS CLI the same way everywhere, fail loudly,
read Terraform outputs, and keep results in build/results/."""
import json
import os
import subprocess
import sys

# The repo folder (where env.sh lives). env.sh exports WORKDIR; fall back to the parent of scripts/.
ROOT = os.environ.get("WORKDIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "build", "results")


def aws(*args):
    """Run `aws <args> --output json` and return parsed JSON (or {} for empty output)."""
    ok, data, err = aws_try(*args)
    if not ok:
        sys.exit(f"\nFAILED: aws {' '.join(args[:2])}\n{err}\n")
    return data


def aws_try(*args):
    """Like aws(), but returns (ok, data, stderr) instead of exiting."""
    res = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True)
    if res.returncode != 0:
        return False, {}, res.stderr.strip()
    return True, (json.loads(res.stdout) if res.stdout.strip() else {}), ""


def tf_output(name):
    """One Terraform output, parsed (run from anywhere: uses the repo's infra/ folder)."""
    res = subprocess.run(["terraform", f"-chdir={os.path.join(ROOT, 'infra')}", "output", "-json", name],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"\nFAILED: terraform output {name}\n{res.stderr.strip()}\n")
    return json.loads(res.stdout)


def write_result(name, obj):
    """build/results/<name>.json, pretty-printed (these files go into the repo)."""
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, f"{name}.json")
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=str)
    return path


def result_lines(text, prefix="RESULT "):
    """The JSON objects printed on lines that start with prefix."""
    return [json.loads(l[len(prefix):]) for l in text.splitlines() if l.startswith(prefix)]


def read_jsonl(name):
    """build/results/<name>.jsonl as a list of dicts ([] if missing)."""
    path = os.path.join(RESULTS, f"{name}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(name, obj):
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, f"{name}.jsonl"), "a") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def read_result(name):
    """build/results/<name>.json parsed, or None."""
    path = os.path.join(RESULTS, f"{name}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


LAB_KEYS = ("phases", "regions", "vpc", "lab", "nat", "buckets", "flow_log_id", "athena", "app_sha256",
            "s3_gateway_endpoint_id")


def lab_info(refresh=False):
    """The Terraform outputs these scripts need, snapshotted in build/results/lab.json. The instances and
    the NAT gateway disappear when traffic_lab = false, so their last known values are kept: the
    forensics still need the NAT gateway's ENI and IP after it's gone."""
    old = read_result("lab") or {}
    if old and not refresh:
        return old
    res = subprocess.run(["terraform", f"-chdir={os.path.join(ROOT, 'infra')}", "output", "-json"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"\nFAILED: terraform output\n{res.stderr.strip()}\n")
    outs = {k: v.get("value") for k, v in json.loads(res.stdout or "{}").items()}
    # terraform output -json leaves out any output whose value is null (lab/nat when traffic_lab is
    # false, the endpoint until its phase is on), so those three may be absent: absent = None.
    missing = [k for k in LAB_KEYS if k not in outs and k not in ("lab", "nat", "s3_gateway_endpoint_id")]
    if missing:
        sys.exit(f"terraform output is missing {missing}: has the base apply run?")
    new = {k: outs.get(k) for k in LAB_KEYS}
    for k in ("lab", "nat"):
        if not new[k] and old.get(k):
            new[k] = old[k]
            new.setdefault("kept_from_earlier", []).append(k)
    write_result("lab", new)
    return new


def mask(text, account_id):
    """Hide the account ID in anything printed or saved."""
    return text.replace(account_id, "<account-id>") if account_id else text
