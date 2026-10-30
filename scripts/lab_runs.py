"""The catalogue of traffic runs: who sends what to whom, how many bytes, which path the bytes
SHOULD take (the forensics check it), and which phase the run needs. Shared by run_traffic.py,
forensics.py and cost_model.py."""

GIB = 1 << 30
MIB = 1 << 20

TOOL = "python3 /opt/mvela/mvela_traffic.py"
PAYLOAD_A = "/var/tmp/mvela/payload.csv"      # 1 GiB on app-a
PAYLOAD_B = "/var/tmp/mvela/payload-b.csv"    # 256 MiB on app-b
PAYLOADS = {"app-a": (PAYLOAD_A, GIB), "app-b": (PAYLOAD_B, 256 * MIB)}

QUIET_GAP_S = 150    # between runs, so flow-log windows (+/- 60 s timing slack) never overlap
WINDOW_PAD_S = 65    # a record belongs to a run if its start is within the run +/- this

# Public, stable HTTPS sources for the internet download (ranged requests, first one that works).
DOWNLOAD_URLS = [
    "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img",
    "https://speed.cloudflare.com/__down?bytes={n}",
]

# expect: direction of the main bytes ("egress", "ingress" or "both" for request/response) and the
# path label the forensics should find on the sender's ENI. endpoint: True/False = the run needs the
# S3 gateway endpoint phase on/off; None = either.
RUNS = {
    "idle": dict(
        order=1, src="app-a", kind="idle", logical=0, timeout=330, endpoint=None,
        expect=None,
        what="4 minutes of nothing: the background (SSM agent etc.) every instance sends through the NAT"),
    "s3-nat": dict(
        order=2, src="app-a", kind="s3", bucket="lake", logical=GIB, timeout=660, endpoint=False,
        expect=("egress", "S3 us-east-1 via NAT gateway"),
        what="app-a uploads 1 GiB to the data lake in us-east-1 - through the NAT gateway"),
    "s3-nat-from-b": dict(
        order=3, src="app-b", kind="s3", bucket="lake", logical=256 * MIB, timeout=660, endpoint=False,
        expect=("egress", "S3 us-east-1 via NAT gateway"),
        what="app-b (AZ b) uploads 256 MiB to the data lake - through the NAT gateway in AZ a"),
    "xaz-bulk": dict(
        order=4, src="app-a", kind="tcp", peer="app-b", logical=GIB, timeout=660, endpoint=None,
        expect=("egress", "cross-AZ"),
        what="app-a sends 1 GiB to app-b (AZ a -> AZ b), private IPs"),
    "saz-bulk": dict(
        order=5, src="app-a", kind="tcp", peer="app-a2", logical=GIB, timeout=660, endpoint=None,
        expect=("egress", "same-AZ"),
        what="app-a sends 1 GiB to app-a2 (same AZ), private IPs"),
    "chatty-xaz": dict(
        order=6, src="app-a", kind="chatty", peer="app-b", logical=32768 * (4096 + 1024), timeout=660,
        endpoint=None, expect=("both", "cross-AZ"),
        what="the chatty service: 32768 HTTP calls (4 KiB request, 1 KiB answer) app-a -> app-b"),
    "chatty-saz": dict(
        order=7, src="app-a", kind="chatty", peer="app-a2", logical=32768 * (4096 + 1024), timeout=660,
        endpoint=None, expect=("both", "same-AZ"),
        what="AZ affinity: the same 32768 calls, app-a -> app-a2 in its own AZ"),
    "s3-euw1-nat": dict(
        order=8, src="app-a", kind="s3", bucket="replica", logical=GIB, timeout=660, endpoint=None,
        expect=("egress", "S3 eu-west-1 via NAT gateway"),
        what="app-a copies the 1 GiB CSV to the replica bucket in eu-west-1 (inter-Region + NAT)"),
    "gzip-euw1": dict(
        order=9, src="app-a", kind="gzip-s3", bucket="replica", logical=None, timeout=900, endpoint=None,
        expect=("egress", "S3 eu-west-1 via NAT gateway"),
        what="the compression fix: the same CSV gzip-compressed, then copied to eu-west-1"),
    "internet-in": dict(
        order=10, src="app-a", kind="download", logical=512 * MIB, timeout=660, endpoint=None,
        expect=("ingress", "internet via NAT gateway"),
        what="app-a downloads 512 MiB from the internet (public HTTPS) - through the NAT gateway"),
    "s3-gwe": dict(
        order=11, src="app-a", kind="s3", bucket="lake", logical=GIB, timeout=660, endpoint=True,
        expect=("egress", "S3 us-east-1 via gateway endpoint"),
        what="the S3 fix: app-a uploads the same 1 GiB to the data lake - through the gateway endpoint"),
    "s3-gwe-from-b": dict(
        order=12, src="app-b", kind="s3", bucket="lake", logical=256 * MIB, timeout=660, endpoint=True,
        expect=("egress", "S3 us-east-1 via gateway endpoint"),
        what="app-b uploads 256 MiB to the data lake - gateway endpoint, no hop to AZ a"),
}


def latest_runs(rows):
    """The last record per run name (a re-run replaces the earlier one), in catalogue order."""
    last = {}
    for r in rows:
        last[r["run"]] = r
    return sorted(last.values(), key=lambda r: RUNS.get(r["run"], {}).get("order", 99))
