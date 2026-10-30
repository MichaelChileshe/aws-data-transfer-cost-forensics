#!/usr/bin/env python3
"""Mvelaphanda traffic tool: the app service on every instance AND the generator of known traffic.
Python 3 standard library only. Every generator prints one line "RESULT {json}" with exact byte
counts and the start/end time (Unix seconds, from the instance clock) of the transfer itself.

  serve                                   TCP sink on 9000 + HTTP service on 8080 (systemd runs this)
  make-payload --bytes N --out F          deterministic shipment-events CSV of exactly N bytes
  tcp-send --host H --bytes N             send exactly N bytes to H:9000, wait for "OK N"
  chatty --host H --calls N               many small HTTP calls to H:8080 (keep-alive, W workers)
  s3-put --file F --bucket B --key K --region R     upload with the AWS CLI on the instance
  gzip --in F --out F.gz                  compress (level 6) and report the ratio
  download --bytes N --url U [--url U2]   exactly N bytes over HTTPS in ranged chunks
  idle --seconds S                        do nothing (the background baseline)
"""
import argparse
import gzip
import hashlib
import http.client
import http.server
import json
import os
import random
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request

CHUNK = 1 << 20  # 1 MiB


def result(obj):
    print("RESULT " + json.dumps(obj, sort_keys=True), flush=True)


def check_deadline(t_start, deadline, what):
    if time.time() - t_start > deadline:
        raise TimeoutError(f"{what}: deadline of {deadline} s passed")


# ---------------------------------------------------------------- serve

class _Sink(socketserver.BaseRequestHandler):
    """Bulk TCP sink: count every byte until the sender closes its side, then answer OK <count>."""

    def handle(self):
        self.request.settimeout(120)
        n = 0
        try:
            while True:
                b = self.request.recv(CHUNK)
                if not b:
                    break
                n += len(b)
            self.request.sendall(f"OK {n}\n".encode())
        except OSError:
            pass


class _Http(http.server.BaseHTTPRequestHandler):
    """POST /call: read the body, answer with X-Resp-Bytes bytes (max 1 MiB). Keep-alive."""
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True  # small request/response pairs: no Nagle + delayed-ACK stalls
    body_cache = {}

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        left = n
        while left > 0:
            got = self.rfile.read(min(left, CHUNK))
            if not got:
                break
            left -= len(got)
        want = max(0, min(int(self.headers.get("X-Resp-Bytes", "256")), CHUNK))
        body = self.body_cache.get(want)
        if body is None:
            body = self.body_cache.setdefault(want, (b'{"status":"ok","pad":"' + b"x" * want)[:want])
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _HTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def cmd_serve(a):
    tcp = _TCPServer(("0.0.0.0", a.tcp_port), _Sink)
    web = _HTTPServer(("0.0.0.0", a.http_port), _Http)
    threading.Thread(target=tcp.serve_forever, daemon=True).start()
    print(f"serving: tcp sink :{a.tcp_port}, http :{a.http_port}", flush=True)
    web.serve_forever()


# ---------------------------------------------------------------- make-payload

DEPOTS = ["JHB-City Deep", "DBN-Bayhead", "CPT-Epping", "PE-Markman", "BFN-Hamilton", "PTA-Rosslyn",
          "PLK-Ladanna", "MBM-Riverside", "EL-Wilsonia", "KIM-Kimdustria"]
STATUSES = ["CREATED", "PICKED_UP", "IN_TRANSIT", "AT_DEPOT", "OUT_FOR_DELIVERY", "DELIVERED", "EXCEPTION"]
CUSTOMERS = [f"CUST-{i:05d}" for i in range(2000)]
NOTES = ["", "", "", "left at reception", "signed by security", "gate code needed", "fragile",
         "cold chain 2-8C", "reschedule requested", "customer not home"]


def cmd_make_payload(a):
    """A deterministic CSV of shipment events, exactly a.bytes long, ending with a newline."""
    t0 = time.time()
    rnd = random.Random(a.seed)
    pool = []
    for _ in range(50000):
        lat = -34.0 + rnd.random() * 12
        lon = 18.0 + rnd.random() * 14
        pool.append(f"SHP{rnd.randrange(10**9):09d},{rnd.choice(DEPOTS)},{rnd.choice(STATUSES)},"
                    f"{lat:.5f},{lon:.5f},{rnd.randrange(1, 30000) / 10:.1f},{rnd.choice(CUSTOMERS)},"
                    f"{rnd.choice(NOTES)}\n")
    header = b"event_id,ts,shipment_id,depot,status,lat,lon,weight_kg,customer,notes\n"
    h = hashlib.sha256()
    written, event, ts = 0, 0, 1767225600
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "wb") as f:
        f.write(header)
        h.update(header)
        written = len(header)
        while True:
            rows = rnd.choices(pool, k=4096)
            block = "".join(f"{event + i},{ts + (event + i) // 7},{r}" for i, r in enumerate(rows)).encode()
            event += len(rows)
            if written + len(block) > a.bytes - 200:
                # finish line by line, then one padding comment line to land on the exact byte count
                for line in block.splitlines(keepends=True):
                    if written + len(line) > a.bytes - 100:
                        break
                    f.write(line)
                    h.update(line)
                    written += len(line)
                pad = a.bytes - written
                tail = (b"#" + b"-" * max(0, pad - 2) + b"\n")[:pad]
                f.write(tail)
                h.update(tail)
                written += len(tail)
                break
            f.write(block)
            h.update(block)
            written += len(block)
    assert written == a.bytes == os.path.getsize(a.out), (written, a.bytes)
    result({"mode": "make-payload", "file": a.out, "bytes": written, "sha256": h.hexdigest(),
            "seconds": round(time.time() - t0, 2)})


# ---------------------------------------------------------------- tcp-send

def cmd_tcp_send(a):
    buf = bytes(range(256)) * (CHUNK // 256)
    s = socket.create_connection((a.host, a.port), timeout=15)
    s.settimeout(30)
    t0 = time.time()
    sent, last = 0, t0
    try:
        while sent < a.bytes:
            n = min(CHUNK, a.bytes - sent)
            s.sendall(buf[:n] if n < CHUNK else buf)
            sent += n
            if time.time() - last > 10:
                print(f"  sent {sent / 2**20:.0f} MiB of {a.bytes / 2**20:.0f} MiB", flush=True)
                last = time.time()
            check_deadline(t0, a.deadline, "tcp-send")
        s.shutdown(socket.SHUT_WR)
        ack = b""
        while not ack.endswith(b"\n"):
            b = s.recv(64)
            if not b:
                break
            ack += b
    finally:
        s.close()
    t1 = time.time()
    acked = int(ack.split()[1]) if ack.startswith(b"OK ") else None
    if acked != sent:
        sys.exit(f"tcp-send: receiver acknowledged {acked}, sent {sent}")
    result({"mode": "tcp-send", "peer": a.host, "port": a.port, "bytes": sent, "acked": acked,
            "t0": round(t0, 3), "t1": round(t1, 3), "seconds": round(t1 - t0, 3),
            "mbit_s": round(sent * 8 / max(t1 - t0, 1e-6) / 1e6, 1)})


# ---------------------------------------------------------------- chatty

class _NoDelayConn(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def cmd_chatty(a):
    """W workers, each with one keep-alive connection, share a.calls POSTs of a.req_bytes; each
    answer is a.resp_bytes. Counts exact payload bytes both ways."""
    body = (b'{"event":"scan","pad":"' + b"y" * a.req_bytes)[:a.req_bytes]
    lock = threading.Lock()
    state = {"next": 0, "ok": 0, "err": 0, "resp_bytes": 0, "errors": [], "t_end": 0.0}
    t0 = time.time()

    def worker():
        conn = _NoDelayConn(a.host, a.port, timeout=15)
        while True:
            with lock:
                if state["next"] >= a.calls or time.time() - t0 > a.deadline:
                    break
                state["next"] += 1
            try:
                conn.request("POST", "/call", body=body, headers={"X-Resp-Bytes": str(a.resp_bytes),
                                                                  "Content-Type": "application/json"})
                r = conn.getresponse()
                data = r.read()
                with lock:
                    state["ok"] += 1
                    state["resp_bytes"] += len(data)
            except (OSError, http.client.HTTPException) as e:
                with lock:
                    state["err"] += 1
                    if len(state["errors"]) < 3:
                        state["errors"].append(repr(e))
                conn.close()
                conn = _NoDelayConn(a.host, a.port, timeout=15)
        conn.close()
        with lock:  # the run ends when the LAST worker finishes, not when the monitor loop notices
            state["t_end"] = max(state["t_end"], time.time())

    threads = [threading.Thread(target=worker) for _ in range(a.workers)]
    for t in threads:
        t.start()
    last = time.time()
    while any(t.is_alive() for t in threads):
        time.sleep(0.5)
        if time.time() - last > 10:
            print(f"  calls done {state['ok']} of {a.calls}", flush=True)
            last = time.time()
    t1 = state["t_end"] or time.time()
    if time.time() - t0 > a.deadline and state["ok"] < a.calls:
        sys.exit(f"chatty: deadline of {a.deadline} s passed after {state['ok']} calls")
    if state["err"]:
        sys.exit(f"chatty: {state['err']} failed calls, e.g. {state['errors']}")
    result({"mode": "chatty", "peer": a.host, "port": a.port, "calls": state["ok"], "workers": a.workers,
            "req_payload_bytes": state["ok"] * a.req_bytes, "resp_payload_bytes": state["resp_bytes"],
            "bytes": state["ok"] * a.req_bytes + state["resp_bytes"],
            "t0": round(t0, 3), "t1": round(t1, 3), "seconds": round(t1 - t0, 3),
            "calls_per_s": round(state["ok"] / max(t1 - t0, 1e-6), 1)})


# ---------------------------------------------------------------- s3-put

def cmd_s3_put(a):
    size = os.path.getsize(a.file)
    cmd = ["aws", "s3", "cp", a.file, f"s3://{a.bucket}/{a.key}", "--region", a.region,
           "--only-show-errors", "--no-progress"]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=a.deadline)
    except subprocess.TimeoutExpired:
        sys.exit(f"s3-put: deadline of {a.deadline} s passed")
    t1 = time.time()
    if p.returncode != 0:
        sys.exit(f"s3-put failed: {p.stderr.strip()[:500]}")
    result({"mode": "s3-put", "bucket": a.bucket, "key": a.key, "region": a.region, "bytes": size,
            "t0": round(t0, 3), "t1": round(t1, 3), "seconds": round(t1 - t0, 3),
            "mbit_s": round(size * 8 / max(t1 - t0, 1e-6) / 1e6, 1)})


# ---------------------------------------------------------------- gzip

def cmd_gzip(a):
    t0 = time.time()
    with open(a.inp, "rb") as src, gzip.open(a.out, "wb", compresslevel=a.level) as dst:
        while True:
            b = src.read(4 * CHUNK)
            if not b:
                break
            dst.write(b)
    t1 = time.time()
    i, o = os.path.getsize(a.inp), os.path.getsize(a.out)
    result({"mode": "gzip", "in_bytes": i, "out_bytes": o, "ratio": round(o / i, 4), "level": a.level,
            "seconds": round(t1 - t0, 2)})


# ---------------------------------------------------------------- download

def cmd_download(a):
    """Fetch exactly a.bytes over HTTPS in ranged chunks of a.chunk bytes; on any error move on to
    the next URL. A server that ignores Range is read only up to the chunk size, then closed."""
    urls = list(a.url)
    got, requests, used = 0, 0, {}
    t0 = time.time()
    last = t0
    while got < a.bytes:
        if not urls:
            sys.exit(f"download: every source failed after {got} bytes")
        want = min(a.chunk, a.bytes - got)
        url = urls[0].replace("{n}", str(want))
        req = urllib.request.Request(url, headers={"Range": f"bytes=0-{want - 1}",
                                                   "User-Agent": "mvela-traffic/1.0"})
        n = 0
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                while n < want:
                    b = r.read(min(CHUNK, want - n))
                    if not b:
                        break
                    n += len(b)
            requests += 1
        except OSError as e:
            print(f"  source failed ({e.__class__.__name__}: {str(e)[:120]}): {urls[0]}", flush=True)
            urls.pop(0)
            got += n
            used[url] = used.get(url, 0) + n
            continue
        got += n
        used[url] = used.get(url, 0) + n
        if n < want:
            print(f"  short read ({n} of {want}) from {urls[0]}, next source", flush=True)
            urls.pop(0)
        if time.time() - last > 10:
            print(f"  downloaded {got / 2**20:.0f} MiB of {a.bytes / 2**20:.0f} MiB", flush=True)
            last = time.time()
        check_deadline(t0, a.deadline, "download")
    t1 = time.time()
    result({"mode": "download", "bytes": got, "requests": requests, "sources": used,
            "t0": round(t0, 3), "t1": round(t1, 3), "seconds": round(t1 - t0, 3),
            "mbit_s": round(got * 8 / max(t1 - t0, 1e-6) / 1e6, 1)})


# ---------------------------------------------------------------- idle

def cmd_idle(a):
    t0 = time.time()
    time.sleep(a.seconds)
    t1 = time.time()
    result({"mode": "idle", "bytes": 0, "t0": round(t0, 3), "t1": round(t1, 3), "seconds": round(t1 - t0, 3)})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--tcp-port", type=int, default=9000)
    s.add_argument("--http-port", type=int, default=8080)
    s = sub.add_parser("make-payload")
    s.add_argument("--bytes", type=int, required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=170)
    s = sub.add_parser("tcp-send")
    s.add_argument("--host", required=True)
    s.add_argument("--port", type=int, default=9000)
    s.add_argument("--bytes", type=int, required=True)
    s.add_argument("--deadline", type=int, default=600)
    s = sub.add_parser("chatty")
    s.add_argument("--host", required=True)
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--calls", type=int, default=32768)
    s.add_argument("--req-bytes", type=int, default=4096)
    s.add_argument("--resp-bytes", type=int, default=1024)
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--deadline", type=int, default=600)
    s = sub.add_parser("s3-put")
    s.add_argument("--file", required=True)
    s.add_argument("--bucket", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--region", required=True)
    s.add_argument("--deadline", type=int, default=600)
    s = sub.add_parser("gzip")
    s.add_argument("--in", dest="inp", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--level", type=int, default=6)
    s = sub.add_parser("download")
    s.add_argument("--bytes", type=int, required=True)
    s.add_argument("--chunk", type=int, default=64 * CHUNK)
    s.add_argument("--url", action="append", required=True)
    s.add_argument("--deadline", type=int, default=600)
    s = sub.add_parser("idle")
    s.add_argument("--seconds", type=int, default=240)
    a = p.parse_args()
    try:
        {"serve": cmd_serve, "make-payload": cmd_make_payload, "tcp-send": cmd_tcp_send, "chatty": cmd_chatty,
         "s3-put": cmd_s3_put, "gzip": cmd_gzip, "download": cmd_download, "idle": cmd_idle}[a.cmd](a)
    except TimeoutError as e:
        sys.exit(str(e))
    except OSError as e:
        sys.exit(f"{a.cmd} failed: {e.__class__.__name__}: {e}")


if __name__ == "__main__":
    main()
