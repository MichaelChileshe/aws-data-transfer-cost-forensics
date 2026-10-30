# 0004: CloudFront is not a cost fix for South African viewers

**Status:** accepted · **Date:** 30 October 2026

## Context

The original plan put CloudFront in front of Mvelaphanda's internet egress (40 TB a month, mostly to South African customers) as a cost saving.

## Decision

Don't count CloudFront as a data-transfer saving. Decide on it for **caching and latency**, and measure the cache hit ratio before claiming any cost benefit.

## Evidence

Price List API, 30 October 2026:
- **CloudFront to viewers in South Africa:** US$0.11/GB for the first 10 TB.
- **us-east-1 to the internet:** US$0.09/GB for the first 10 TB.

Projection, after compression (16.945 TB a month):
- **Through CloudFront:** US$1,765.61.
- **Straight from us-east-1:** US$1,517.59.
- **Total "after" bill:** US$2,887.04 with CloudFront, US$2,639.02 without.

## Consequences

- CloudFront can still lower the bill if caching cuts the bytes leaving the origin. That depends on a hit ratio this lab doesn't measure.
- Latency to South African users, TLS termination at the edge, and shielding the origin are separate reasons to use it. They should be argued on their own.
