-- Every hop between two ENIs inside the VPC, counted ONCE, with the AZ at each end:
--   instance -> instance : the sender's egress record (dstaddr is the other instance)
--   instance -> NAT      : the NAT ENI's record with dstaddr = NAT private IP (the instance's own
--                          record shows the final destination, e.g. S3, so the hop is only visible here)
--   NAT -> instance      : the NAT ENI's record with srcaddr = NAT private IP, dstaddr in the VPC
-- from_az <> to_az = cross-AZ data transfer, billed per GB on BOTH sides.
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
),
hops AS (
  SELECT f."start", f.srcaddr AS hop_src, f.dstaddr AS hop_dst, f.az_id AS from_az, p.az_id AS to_az, f.bytes, f.packets
  FROM f JOIN ipaz p ON p.ip = f.dstaddr
  WHERE f.instance_id IS NOT NULL AND f.instance_id <> '-' AND f.flow_direction = 'egress'
  UNION ALL
  SELECT n."start", n.srcaddr, n.dstaddr, p.az_id, n.az_id, n.bytes, n.packets
  FROM f n JOIN ipaz p ON p.ip = n.srcaddr
  WHERE n.interface_id = 'eni-0bbc0dba041f72507' AND n.dstaddr = '10.170.0.151'
  UNION ALL
  SELECT n."start", n.srcaddr, n.dstaddr, n.az_id, p.az_id, n.bytes, n.packets
  FROM f n JOIN ipaz p ON p.ip = n.dstaddr
  WHERE n.interface_id = 'eni-0bbc0dba041f72507' AND n.srcaddr = '10.170.0.151'
)
SELECT coalesce(r.run, '(between runs)') AS run,
       h.hop_src,
       h.hop_dst,
       h.from_az,
       h.to_az,
       CASE WHEN h.from_az = h.to_az THEN 'same-AZ' ELSE 'cross-AZ' END AS kind,
       sum(h.bytes) AS bytes,
       sum(h.packets) AS packets
FROM hops h
LEFT JOIN runs r ON h."start" BETWEEN r.t0 - 65 AND r.t1 + 65
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY 1, 7 DESC

