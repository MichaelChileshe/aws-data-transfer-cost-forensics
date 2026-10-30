# 0001: An S3 gateway endpoint in every VPC that uses S3

**Status:** accepted · **Date:** 30 October 2026

## Context

Mvelaphanda's private subnets reach S3 through the NAT gateway. S3 traffic within the Region has no transfer charge, but the NAT gateway charges US$0.045 for every GB it processes. In the profile, that's 60 TB a month to the data lake.

## Decision

Add an **S3 gateway endpoint** to every VPC that talks to S3, on every private route table.

## Evidence

From the lab, the same uploads before and after:
- **1 GiB to S3 through the NAT:** NAT processed 1,097,533,089 bytes, costing **US$0.0460**.
- **The same upload through the gateway endpoint:** NAT processed 39,361 bytes (background), costing **US$0.0000**.
- **256 MiB from the other AZ:** US$0.0167 through the NAT (processing plus a cross-AZ hop), **US$0.0000** through the endpoint. The hop went from 275,161,240 bytes to 10,205.
- **The endpoint itself:** no hourly or per-GB charge. Terraform: `1 to add`.

## Consequences

- Only same-Region S3 is affected. S3 in other Regions (the eu-west-1 replica) still goes through the NAT gateway; the endpoint's route only covers this Region's S3 prefix list.
- Endpoint policies and bucket policies (for example `aws:SourceVpce`) become available to restrict S3 access to the VPC.
- DynamoDB has the same kind of free gateway endpoint; other services need interface endpoints, which do charge.
