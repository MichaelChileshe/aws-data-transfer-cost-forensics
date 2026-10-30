# 0002: A NAT gateway per AZ, and keep service calls in their own AZ

**Status:** accepted · **Date:** 30 October 2026

## Context

Mvelaphanda runs one NAT gateway, in AZ a, for both AZs. AZ b's outbound traffic crosses to AZ a first. Services call each other without regard to AZ, so about half of 100 TB a month of service calls cross AZs.

## Decision

1. Run **one NAT gateway per AZ**, each private subnet routing to the NAT gateway in its own AZ.
2. **Prefer same-AZ targets for service-to-service calls,** through load balancer or service-discovery settings that keep traffic in-zone. Aim for a cross-AZ share of about 5%.

## Evidence

From the lab:
- **1 GiB between instances:** US$0.0201 across AZs (US$0.01/GB on each side), US$0.0000 within one AZ.
- **32,768 chatty HTTP calls:** US$0.0035 across AZs, US$0.0000 within one AZ. The wire carried 12% more than the payload, all billable when it crosses.
- **AZ b to S3 through the NAT gateway in AZ a:** a 275 MB cross-AZ hop on a 256 MiB upload, so US$0.0666 per GB sent instead of US$0.046.

From the projection:
- **Cross-AZ hop to the NAT gateway:** US$1,075.61 a month → 0.
- **Service calls across AZs:** US$1,024.00 → US$102.40.
- **NAT hours:** go up by US$32.85 a month for the second gateway.

## Consequences

- Each AZ fails independently for outbound traffic, which is also the resilient design.
- AZ affinity has to keep enough capacity in each AZ. If one AZ's targets fail, traffic should still cross rather than fail.
