-- Every hop between two ENIs inside the VPC, counted ONCE, with the AZ at each end:
--   instance -> instance : the sender's egress record (dstaddr is the other instance)
--   instance -> NAT      : the NAT ENI's record with dstaddr = NAT private IP (the instance's own
--                          record shows the final destination, e.g. S3, so the hop is only visible here)
--   NAT -> instance      : the NAT ENI's record with srcaddr = NAT private IP, dstaddr in the VPC
-- from_az <> to_az = cross-AZ data transfer, billed per GB on BOTH sides.
WITH {{BASE}},
hops AS (
  SELECT f."start", f.srcaddr AS hop_src, f.dstaddr AS hop_dst, f.az_id AS from_az, p.az_id AS to_az, f.bytes, f.packets
  FROM f JOIN ipaz p ON p.ip = f.dstaddr
  WHERE f.instance_id IS NOT NULL AND f.instance_id <> '-' AND f.flow_direction = 'egress'
  UNION ALL
  SELECT n."start", n.srcaddr, n.dstaddr, p.az_id, n.az_id, n.bytes, n.packets
  FROM f n JOIN ipaz p ON p.ip = n.srcaddr
  WHERE n.interface_id = '{{NAT_ENI}}' AND n.dstaddr = '{{NAT_IP}}'
  UNION ALL
  SELECT n."start", n.srcaddr, n.dstaddr, n.az_id, p.az_id, n.bytes, n.packets
  FROM f n JOIN ipaz p ON p.ip = n.dstaddr
  WHERE n.interface_id = '{{NAT_ENI}}' AND n.srcaddr = '{{NAT_IP}}'
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
LEFT JOIN runs r ON h."start" BETWEEN r.t0 - {{PAD}} AND r.t1 + {{PAD}}
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY 1, 7 DESC
