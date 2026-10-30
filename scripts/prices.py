#!/usr/bin/env python3
"""Current list prices from the AWS Price List API (aws pricing get-products, endpoint us-east-1).
Every lookup pins the service code + the billing usage type (+ product family where there is one) and
must match EXACTLY ONE product with exactly one on-demand term: zero or several matches is an error,
never a guess. Every raw record returned is saved to build/results/prices-raw.json.

  python3 scripts/prices.py
  python3 scripts/prices.py --pin KEY:Field=Value [...]   # extra filter if a lookup matched several

Usage types in us-east-1 carry NO Region prefix (DataTransfer-Regional-Bytes, NatGateway-Bytes);
inter-Region ones name both Regions (USE1-EU-AWS-Out-Bytes: eu-west-1's billing code is EU). The Price List API itself is free.
"""
import json
import re
import sys
from datetime import datetime, timezone

from kit_aws import aws, write_result

# Billing usage types use the Region's billing code, and eu-west-1's is the old "EU", not "EUW1"
# (the first lookup with EUW1 matched nothing). us-east-1 has no prefix on its own usage types.
DT_SERVICES = ["AWSDataTransfer", "AmazonEC2"]  # data transfer products moved to AWSDataTransfer; EC2 as 2nd

# key: (service codes to try in order, filters, required for the cost model, what it is)
LOOKUPS = {
    "nat_hour": (["AmazonEC2"], {"usagetype": "NatGateway-Hours", "productFamily": "NAT Gateway"}, True,
                 "NAT gateway, per hour (us-east-1)"),
    "nat_gb": (["AmazonEC2"], {"usagetype": "NatGateway-Bytes", "productFamily": "NAT Gateway"}, True,
               "NAT gateway, per GB processed (us-east-1)"),
    "intra_region_gb": (DT_SERVICES, {"usagetype": "DataTransfer-Regional-Bytes"}, True,
                        "inter-AZ in us-east-1, per GB, each direction"),
    "use1_to_euw1_gb": (DT_SERVICES, {"usagetype": "USE1-EU-AWS-Out-Bytes"}, True,
                        "us-east-1 -> eu-west-1, per GB"),
    "euw1_to_use1_gb": (DT_SERVICES, {"usagetype": "EU-USE1-AWS-Out-Bytes"}, True,
                        "eu-west-1 -> us-east-1, per GB (S3 answers coming back)"),
    "internet_out": (DT_SERVICES, {"usagetype": "DataTransfer-Out-Bytes"}, True,
                     "us-east-1 -> internet, per GB, tiered"),
    "internet_in": (DT_SERVICES, {"usagetype": "DataTransfer-In-Bytes"}, True,
                    "internet -> us-east-1, per GB"),
}
# CloudFront edge pricing is per viewer location; its usage types are "<code>-DataTransfer-Out-Bytes".
CLOUDFRONT = {"cf_south_africa": "South Africa", "cf_united_states": "United States"}

RAW = []


def get_products(service, filters):
    args = ["pricing", "get-products", "--region", "us-east-1", "--service-code", service,
            "--format-version", "aws_v1", "--filters"]
    args += [f"Type=TERM_MATCH,Field={k},Value={v}" for k, v in filters.items()]
    plist = aws(*args).get("PriceList", [])
    prods = [json.loads(p) if isinstance(p, str) else p for p in plist]
    RAW.append({"service": service, "filters": filters, "records": prods})
    return prods


def dimensions(prod):
    od = prod.get("terms", {}).get("OnDemand", {})
    if len(od) != 1:
        raise ValueError(f"{len(od)} on-demand terms")
    dims = []
    for d in next(iter(od.values()))["priceDimensions"].values():
        end = d.get("endRange", "Inf")
        dims.append({"begin": float(d.get("beginRange", 0)), "end": None if end == "Inf" else float(end),
                     "usd": float(d["pricePerUnit"]["USD"]), "unit": d.get("unit"),
                     "description": d.get("description")})
    return sorted(dims, key=lambda x: x["begin"])


def summarise(key, service, filters, prod, what):
    dims = dimensions(prod)
    attrs = prod.get("product", {}).get("attributes", {})
    out = {"what": what, "service": service, "filters": filters, "sku": prod.get("product", {}).get("sku"),
           "usagetype": attrs.get("usagetype"), "operation": attrs.get("operation"),
           "location": attrs.get("location") or attrs.get("fromLocation"), "unit": dims[0]["unit"]}
    if len(dims) == 1:
        out["usd"] = dims[0]["usd"]
    else:
        out["tiers"] = [{"begin_gb": d["begin"], "end_gb": d["end"], "usd": d["usd"]} for d in dims]
    return out


def tier_text(t):
    end = "inf" if t["end_gb"] is None else f"{t['end_gb']:.0f}"
    return f"{t['begin_gb']:.0f}-{end} GB US${t['usd']:.4f}"


def distinct(prods):
    """The attributes that differ between several matching products (to choose a --pin)."""
    attrs = [p.get("product", {}).get("attributes", {}) for p in prods]
    keys = sorted({k for a in attrs for k in a if len({b.get(k) for b in attrs}) > 1})
    return [{k: a.get(k) for k in keys} for a in attrs]


def lookup(key, services, filters, what):
    for svc in services:
        prods = get_products(svc, filters)
        if len(prods) == 1:
            return summarise(key, svc, filters, prods[0], what), None
        if len(prods) > 1:
            return None, (f"{key}: {len(prods)} products match {svc} {filters} - pin one more attribute, e.g. "
                          f"--pin {key}:<Field>=<Value>. They differ in: {json.dumps(distinct(prods))[:900]}")
    return None, f"{key}: no product matches {filters} in {services}"


def main():
    pins = {}
    for a in sys.argv[1:]:
        if a == "--pin":
            continue
        m = re.match(r"^([a-z_0-9]+):([A-Za-z]+)=(.+)$", a)
        if not m:
            sys.exit(__doc__)
        pins.setdefault(m[1], {})[m[2]] = m[3]
    prices, errors, warnings = {}, [], []
    for key, (services, filters, required, what) in LOOKUPS.items():
        p, err = lookup(key, services, {**filters, **pins.get(key, {})}, what)
        if p:
            prices[key] = p
        elif required:
            errors.append(err)
        else:
            warnings.append(err)
    # CloudFront: find the "<code>-DataTransfer-Out-Bytes" usage types, then the one per location.
    vals = aws("pricing", "get-attribute-values", "--region", "us-east-1", "--service-code", "AmazonCloudFront",
               "--attribute-name", "usagetype").get("AttributeValues", [])
    cf_types = sorted(v["Value"] for v in vals if re.match(r"^[A-Z0-9]+-DataTransfer-Out-Bytes$", v["Value"]))
    found = {k: [] for k in CLOUDFRONT}
    for ut in cf_types:
        flt = {"usagetype": ut}
        prods = get_products("AmazonCloudFront", flt)
        if len(prods) != 1:
            warnings.append(f"CloudFront {ut}: {len(prods)} products (skipped)")
            continue
        loc = prods[0].get("product", {}).get("attributes", {})
        loc_text = " ".join(str(loc.get(k, "")) for k in ("fromLocation", "location"))
        for key, place in CLOUDFRONT.items():
            if place in loc_text:
                found[key].append(summarise(key, "AmazonCloudFront", flt, prods[0], f"CloudFront to viewers in {place}"))
    for key, hits in found.items():
        if len(hits) == 1:
            prices[key] = hits[0]
        else:
            errors.append(f"{key}: {len(hits)} CloudFront usage types match '{CLOUDFRONT[key]}' "
                          f"({[h['usagetype'] for h in hits]}); expected exactly one")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_result("prices-raw", {"fetched_utc": now, "lookups": RAW})
    out = {"fetched_utc": now, "prices": prices, "errors": errors, "warnings": warnings,
           "documented": {
               "s3_gateway_endpoint": "no hourly or data processing charge (Amazon VPC pricing page)",
               "internet_out_free_gb_month": 100,
               "internet_out_free_note": "100 GB/month free data transfer out to the internet, aggregated across "
                                         "services and Regions (except China and GovCloud)",
               "cloudfront_free_gb_month": 1024,
               "cloudfront_free_note": "CloudFront pay-as-you-go free tier: 1 TB data transfer out per month; "
                                       "origin fetches from AWS origins are free",
               "gb": "1 GB = 2^30 bytes in these calculations"}}
    write_result("prices", out)
    print(f"== Price List API, fetched {now}")
    for k, p in prices.items():
        v = f"US${p['usd']:.4f} per {p['unit']}" if "usd" in p else "tiers: " + ", ".join(tier_text(t) for t in p["tiers"])
        print(f"  {k:<20} {p['usagetype']:<34} {v}   ({p['what']})")
    for w in warnings:
        print(f"  note: {w}")
    print("saved build/results/prices.json and prices-raw.json (every raw record)")
    if errors:
        print("\nPRICES MISSING OR AMBIGUOUS - the cost model will not run until these are fixed:")
        for e in errors:
            print("  - " + e)
        sys.exit(1)


if __name__ == "__main__":
    main()
