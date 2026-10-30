-- The IP -> AZ map the other queries learn from the flow logs (compared with Terraform's own view).
WITH f AS (
  SELECT interface_id, instance_id, az_id, flow_direction, traffic_path, srcaddr, dstaddr, srcport,
         dstport, protocol, packets, bytes, "start", "end", pkt_srcaddr, pkt_dstaddr,
         pkt_src_aws_service, pkt_dst_aws_service
  FROM mvela_xfer.vpc_flow_logs
  WHERE (("year" = '2026' AND "month" = '10' AND "day" = '30' AND "hour" BETWEEN '11' AND '12'))
    AND vpc_id = 'vpc-084d6659fc4b29b32'
    AND log_status = 'OK'
    AND "start" BETWEEN 1793360319 AND 1793364175
),
runs (run, t0, t1) AS (
  VALUES ('idle', 1793360919, 1793361160), ('s3-nat', 1793361336, 1793361340), ('s3-nat-from-b', 1793361499, 1793361501), ('xaz-bulk', 1793361660, 1793361662), ('saz-bulk', 1793361822, 1793361825), ('chatty-xaz', 1793361983, 1793361992), ('chatty-saz', 1793362150, 1793362159), ('s3-euw1-nat', 1793362314, 1793362322), ('gzip-euw1', 1793362521, 1793362525), ('internet-in', 1793362708, 1793362721), ('s3-gwe', 1793363099, 1793363107), ('s3-gwe-from-b', 1793363274, 1793363276)
),
ipaz AS (
  SELECT ip, max(az_id) AS az_id
  FROM (SELECT CASE WHEN flow_direction = 'egress' THEN srcaddr ELSE dstaddr END AS ip, az_id FROM f) x
  WHERE ip LIKE '10.170.%'
  GROUP BY ip
),
inst AS (
  SELECT f.*,
         CASE WHEN flow_direction = 'egress' THEN dstaddr ELSE srcaddr END AS peer,
         CASE WHEN flow_direction = 'egress' THEN pkt_dst_aws_service ELSE pkt_src_aws_service END AS peer_service,
         max(CASE WHEN flow_direction = 'egress' THEN traffic_path END) OVER (
           PARTITION BY interface_id, protocol,
             least(srcaddr || ':' || CAST(srcport AS varchar), dstaddr || ':' || CAST(dstport AS varchar)),
             greatest(srcaddr || ':' || CAST(srcport AS varchar), dstaddr || ':' || CAST(dstport AS varchar))
         ) AS conv_path
  FROM f
  WHERE instance_id IS NOT NULL AND instance_id <> '-'
)
SELECT ip, az_id FROM ipaz ORDER BY ip

