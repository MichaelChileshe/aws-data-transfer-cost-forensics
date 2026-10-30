# 0003: Compress text before it crosses a Region boundary

**Status:** accepted · **Date:** 30 October 2026

## Context

Mvelaphanda copies 30 TB a month of mostly text (CSV, JSON) to eu-west-1. Every GB pays the inter-Region rate (US$0.02 from us-east-1), and today also NAT processing.

## Decision

Compress compressible data **before** it leaves the Region. Replicate with S3 Cross-Region Replication rather than copying from instances through the NAT gateway.

## Evidence

From the lab, on a 1 GiB shipment-events CSV:
- **gzip:** 1,073,741,824 → 300,144,888 bytes (**0.2795**), 44.07 s elapsed on a t4g.small.
- **Raw copy to eu-west-1:** **US$0.0679** (NAT US$0.0470 + inter-Region US$0.0209).
- **Compressed copy:** **US$0.0190**, 72% less.
- **Projection** (80% of the bytes compressible): inter-Region US$614.40 → US$260.28 a month.

## Consequences

- Compute time is the price: 44 s per GiB on a small instance. At 30 TB a month that is real compute, and it belongs on a batch job or the producer, not on a latency-sensitive path.
- Readers in eu-west-1 must decompress, or the data must be stored compressed in a format the readers understand (gzip CSV, Parquet).
- Already-compressed data (images, archives) gains nothing.
