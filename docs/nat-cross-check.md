# Second source: the NAT gateway's own metrics

A forensic method needs a second witness. The NAT gateway publishes its own byte counts to CloudWatch (`AWS/NATGateway`), in the same four directions I split its flow records into. `nat_metrics.py` read them at 1-minute resolution with `get-metric-data` and summed each run's minutes.

**Matching minutes to runs:**
- A minute belongs to a run if it overlaps the run's start to its end plus 60 s; with 150 s between runs, no minute can belong to two.
- Every CloudWatch timestamp is converted to UTC before it's compared: the AWS CLI can return CloudWatch times in the local time zone.

Screenshots [`17`](screenshots/17-nat-legs.png) (flow logs) and [`18`](screenshots/18-nat-cloudwatch.png) (CloudWatch). Data: [`results/nat-metrics.json`](results/nat-metrics.json).

| Run | CloudWatch processed | Flow logs processed | Difference |
|---|---|---|---|
| s3-nat | 1,097,532,620 | 1,097,533,089 | 469 bytes (0.00004%) |
| s3-nat-from-b | 275,141,651 | 275,172,289 | −0.011% |
| s3-euw1-nat | 1,121,244,613 | 1,120,817,728 | +0.038% |
| gzip-euw1 | 313,606,699 | 314,018,431 | −0.131% |
| internet-in | 558,926,130 | 558,929,849 | −0.0007% |
| idle | 111,700 | 103,561 | |
| xaz-bulk / saz-bulk | 36,539 / 59,887 | 39,399 / 62,462 | |
| chatty-xaz / chatty-saz | 37,518 / 25,722 | 41,419 / 28,291 | |
| s3-gwe / s3-gwe-from-b | 51,444 / 13,703 | 39,361 / 26,306 | |

"Processed" is `BytesInFromSource + BytesInFromDestination`: what `NatGateway-Bytes` bills.

**What it shows:**
- **For every run that moved real data through the NAT gateway, the two sources agree within 0.13%.** Two different systems, counting independently, put the same bytes on the same path. That's what makes the flow-log analysis trustworthy enough to price.
- **The directions agree too.** For `s3-nat`, CloudWatch has 1,092,471,192 bytes in from the instance and 1,092,471,192 out to S3. The flow logs have 1,092,476,929 and 1,092,467,616.
- **The small runs differ by a few KB either way.** These are background traffic, and they depend on which minute a 60-second flow record or a 1-minute metric happens to fall into.
- **"Between runs" isn't comparable** (CloudWatch 92,006,705, flow logs 172,348,205). The flow-log analysis window starts 10 minutes before the first run and ends 15 minutes after the last; the CloudWatch query covers 5 minutes before to 10 minutes after. They count different stretches of time.
