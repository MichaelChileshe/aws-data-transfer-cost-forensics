#!/usr/bin/env python3
"""Regenerates docs/architecture.svg + docs/architecture.png using the OFFICIAL AWS Architecture Icons.

The icon pack is not committed (AWS licenses it for diagrams, not redistribution). Download it from
https://aws.amazon.com/architecture/icons/, unzip, then:

    AWS_ICONS_DIR=/path/to/unzipped-icon-package python3 build_architecture.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from awsdiag import Diagram, GREY, INK

NAT, XAZ, OK, S3C, IAC, OPS, NET = ("#D13212", "#ED7100", "#1D8102", "#7AA116", "#7B42BC", "#E7157B", "#8C4FFF")
d = Diagram(1900, 1240)
d.text(40, 40, "Data-transfer cost forensics: every byte traced to a path with VPC Flow Logs and Athena, "
               "priced, fixed, measured again", 19, "bold")
d.text(40, 64, "Mvelaphanda Logistics  ·  us-east-1 VPC 10.170.0.0/16 (use1-az1 = us-east-1a, use1-az2 = us-east-1b)  ·  "
               "replica bucket in eu-west-1  ·  built and destroyed with Terraform, 30 October 2026", 13, "normal", GREY)


def node(key, x, y, title, lines=(), color=INK, size=40, gap=15):
    d.icon(key, x, y, size)
    d.text(x + size + 10, y + 15, title, 12.5, "bold", color)
    for i, l in enumerate(lines):
        d.text(x + size + 10, y + 32 + i * gap, l, 11, "normal", GREY)


# ---------------------------------------------------------------- my machine
d.box(40, 100, 290, 470, IAC, fill="#F7F2FC", dashed=False)
d.text(56, 126, "My machine (WSL)", 13.5, "bold", IAC)
d.icon("client", 56, 140, 40)
d.text(106, 158, "terraform plan / apply / destroy", 12, "bold", INK)
d.text(106, 174, "phases in phases.auto.tfvars", 11, "normal", GREY)
for i, l in enumerate(["s3_gateway_endpoint = true  (the S3 fix)", "traffic_lab = false  (stop the meter)"]):
    d.text(56, 204 + i * 16, l, 11, "normal", GREY)
d.text(56, 252, "the drills run as Python scripts:", 12, "bold", INK)
for i, l in enumerate(["lab_status   (instances, NAT ENI, flow log)", "run_traffic  (12 runs, exact bytes,",
                       "              150 s quiet gap between runs)", "forensics    (6 SQL files in Athena)",
                       "nat_metrics  (NAT CloudWatch, 2nd source)", "prices       (Price List API)",
                       "cost_model   (per run + the month)", "results      (every number, one list)"]):
    d.text(56, 270 + i * 16, l, 11, "normal", GREY)
d.text(56, 418, "no SSH, no inbound admin port:", 12, "bold", INK)
d.text(56, 436, "commands reach the instances", 11, "normal", GREY)
d.text(56, 452, "through SSM (via the NAT gateway)", 11, "normal", GREY)
d.text(56, 486, "profile/mvelaphanda-traffic.json:", 12, "bold", INK)
d.text(56, 504, "the company's monthly traffic,", 11, "normal", GREY)
d.text(56, 520, "used for the before/after projection", 11, "normal", GREY)

node("internet", 56, 610, "Public internet", ["512 MiB HTTPS download", "(cloud-images.ubuntu.com)"], NAT, 40)

# ---------------------------------------------------------------- AWS
d.group("cloud", 360, 90, 1110, 1130, "AWS Cloud")
d.group("region", 380, 135, 1070, 880, "us-east-1")
d.group("vpc", 400, 180, 700, 520, "mvela-xfer VPC 10.170.0.0/16  (one private route table for both AZs)")
node("igw", 420, 220, "Internet gateway", [], NET, 32)
node("vpc_endpoints", 760, 220, "S3 gateway endpoint (the fix)", ["route to S3 us-east-1, free"], OK, 32)

# AZ a
d.box(415, 270, 330, 415, "#00A4A6", fill="none", dashed=True)
d.text(427, 289, "use1-az1 (us-east-1a)", 12.5, "bold", "#00A4A6")
d.group("public", 428, 300, 304, 110, "Public 10.170.0.0/24")
node("nat_gw", 444, 340, "NAT gateway + Elastic IP", ["10.170.0.151, one for the whole VPC",
                                                     "US$0.045 / hour + US$0.045 / GB"], NAT, 36)
d.group("private", 428, 425, 304, 245, "Private a 10.170.10.0/24")
node("ec2_instance", 444, 465, "app-a 10.170.10.10", ["t4g.small: sender of most runs"], INK, 36)
node("ec2_instance", 444, 545, "app-a2 10.170.10.20", ["same AZ as app-a"], INK, 36)
d.text(444, 632, "same-AZ, private IPs: free", 11.5, "bold", OK)
d.line([(470, 505), (470, 541)], OK, width=2)

# AZ b
d.box(760, 270, 325, 415, "#00A4A6", fill="none", dashed=True)
d.text(772, 289, "use1-az2 (us-east-1b)", 12.5, "bold", "#00A4A6")
d.group("private", 773, 425, 300, 245, "Private b 10.170.11.0/24")
node("ec2_instance", 789, 465, "app-b 10.170.11.10", ["receiver; and a 2nd S3 sender"], INK, 36)
d.text(789, 548, "cross-AZ: US$0.01/GB", 11.5, "bold", XAZ)
d.text(789, 564, "on EACH side", 11.5, "bold", XAZ)
d.text(789, 596, "its NAT route crosses to", 11, "normal", GREY)
d.text(789, 612, "AZ a too (another cross-AZ hop)", 11, "normal", GREY)
d.line([(662, 480), (785, 480)], XAZ, width=2.2)
d.line([(825, 461), (825, 400), (700, 360)], XAZ, width=2, dashed=True)
d.line([(462, 461), (462, 380)], NAT, width=2.2)
d.line([(450, 338), (440, 256)], NAT, width=2.2)

# regional services
node("s3_bucket", 1120, 190, "Data lake mvela-xfer-lake-(suffix)", ["same-Region S3: free transfer,",
                                                                     "but NAT-processed unless the endpoint"], S3C, 36)
node("flow_logs", 1120, 270, "VPC Flow Logs, every ENI", ["25 fields (v5), Parquet, hourly", "Hive partitions, 60 s aggregation"],
     OPS, 36)
node("s3_bucket", 1120, 345, "Flow-log bucket", ["lifecycle 7 days"], OPS, 36)
node("glue_catalog", 1120, 410, "Glue table (partition projection)", ["no crawler, no MSCK REPAIR"], OPS, 36)
node("athena", 1120, 475, "Athena workgroup mvela-xfer", ["100 MiB scan limit per query",
                                                         "6 queries scanned 0.64 MB in all"], OPS, 36)
node("cloudwatch", 1120, 545, "CloudWatch AWS/NATGateway", ["the NAT's own byte counts,", "a second source per run"],
     OPS, 36)
node("data_table", 1120, 620, "Price List API", ["NAT, cross-AZ, inter-Region,", "internet, CloudFront prices"], OPS, 36)
d.line([(1032, 228), (1116, 210)], OK, width=2.2)

# drill sequence
d.box(400, 720, 1035, 280, "#D5DBDB", fill="#fff", dashed=False)
d.text(416, 744, "12 runs from app-a / app-b (UTC), 150 s apart so each has its own flow-log window", 13, "bold")
seq = [
    ("idle", "11:48", "240 s of nothing: the background every instance sends"),
    ("s3-nat / s3-nat-from-b", "11:55", "1 GiB / 256 MiB to S3 us-east-1 through the NAT"),
    ("xaz-bulk / saz-bulk", "12:01", "1 GiB to app-b (other AZ) / app-a2 (same AZ)"),
    ("chatty-xaz / chatty-saz", "12:06", "32,768 HTTP calls, 4 KiB request + 1 KiB answer"),
    ("s3-euw1-nat", "12:11", "1 GiB CSV to the replica bucket in eu-west-1"),
    ("gzip-euw1", "12:15", "the same CSV gzipped first: 0.2795 of the size"),
    ("internet-in", "12:18", "512 MiB downloaded from the internet through the NAT"),
    ("(endpoint on)", "", "s3_gateway_endpoint = true: 1 added"),
    ("s3-gwe / s3-gwe-from-b", "12:24", "the S3 uploads again, through the gateway endpoint"),
]
for i, (a, t, b) in enumerate(seq):
    y = 770 + i * 24
    d.text(420, y, a, 11.5, "bold", INK)
    d.text(620, y, t, 11.5, "bold", IAC)
    d.text(680, y, b, 11, "normal", GREY)

d.group("region", 380, 1035, 1070, 165, "eu-west-1")
node("s3_bucket", 420, 1085, "Replica bucket mvela-xfer-replica-(suffix)", [
    "us-east-1 -> eu-west-1: US$0.02/GB (usage type USE1-EU-AWS-Out-Bytes), plus NAT processing in us-east-1"], S3C, 40)

# ---------------------------------------------------------------- measured panel
bx, by = 1490, 90
d.box(bx, by, 390, 1130, "#D5DBDB", fill="#fff", dashed=False)
d.text(bx + 14, by + 26, "Measured (one build, 30 October 2026)", 14, "bold")
res = [
    ("1 GiB to S3 us-east-1", NAT, ["through the NAT: US$0.0460", "through the gateway endpoint: US$0.0000",
                                   "NAT processed 1,097,533,089 vs 39,361 B"]),
    ("256 MiB to S3 from AZ b", XAZ, ["NAT in AZ a: US$0.0167 (NAT + cross-AZ hop)", "endpoint: US$0.0000, hop gone"]),
    ("1 GiB between instances", XAZ, ["cross-AZ US$0.0201 · same-AZ US$0.0000", "flow logs 1.0059 x the payload"]),
    ("Chatty service, 32,768 calls", XAZ, ["cross-AZ US$0.0035 · same-AZ US$0.0000", "headers: 1.12 x the payload"]),
    ("1 GiB to eu-west-1", NAT, ["raw US$0.0679 · gzipped first US$0.0190", "gzip: 0.2795 of the size, 44 s CPU"]),
    ("512 MiB from the internet", NAT, ["inbound transfer free; NAT: US$0.0234"]),
    ("Second source agrees", OK, ["NAT CloudWatch vs flow logs, big runs:", "within 0.13% (s3-nat: 469 bytes apart)"]),
    ("Mvelaphanda's month (my profile)", OPS, ["US$11,111.41 -> 2,887.04 (74.0%)", "without CloudFront: 2,639.02 (76.2%)",
                                               "CloudFront ZA costs more per GB here"]),
    ("Terraform", IAC, ["base 44 added (state 48) · endpoint +1", "stop the meter: 6 destroyed (43)",
                        "Destroy complete! 39 destroyed"]),
]
y = by + 58
for title, c, ls in res:
    d.text(bx + 14, y, title, 12, "bold", c)
    for l in ls:
        y += 16
        d.text(bx + 14, y, l, 11.2)
    y += 24

here = os.path.dirname(os.path.abspath(__file__))
d.save(os.path.join(here, "..", "architecture.svg"), os.path.join(here, "..", "architecture.png"))
print("wrote docs/architecture.svg and docs/architecture.png")
