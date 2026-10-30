#!/usr/bin/env python3
"""Copy build/results/ to build/results-masked/ with the account ID replaced by <account-id> in every
text file (json, jsonl, csv, txt, sql), then pack it for the repo.

  python3 scripts/pack_results.py ~/Downloads/data-transfer-results.tar.gz
"""
import os
import shutil
import sys
import tarfile

from kit_aws import RESULTS, ROOT, aws, mask


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    acct = os.environ.get("ACCOUNT_ID") or aws("sts", "get-caller-identity")["Account"]
    if not acct.isdigit():
        sys.exit("could not get the account ID (source ./env.sh first)")
    dst = os.path.join(ROOT, "build", "results-masked")
    shutil.rmtree(dst, ignore_errors=True)
    hits = files = 0
    for base, _, names in os.walk(RESULTS):
        for n in names:
            src = os.path.join(base, n)
            out = os.path.join(dst, os.path.relpath(src, RESULTS))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(src, "rb") as f:
                data = f.read()
            try:
                text = data.decode()
                hits += text.count(acct)
                data = mask(text, acct).encode()
            except UnicodeDecodeError:
                pass
            with open(out, "wb") as f:
                f.write(data)
            files += 1
    left = 0
    for base, _, names in os.walk(dst):
        for n in names:
            with open(os.path.join(base, n), "rb") as f:
                left += f.read().count(acct.encode())
    if left:
        sys.exit(f"account ID still present {left} time(s) in build/results-masked: not packing")
    with tarfile.open(sys.argv[1], "w:gz") as t:
        t.add(dst, arcname="results")
    print(f"{files} files, account ID masked {hits} time(s), 0 left -> {sys.argv[1]}")


if __name__ == "__main__":
    main()
