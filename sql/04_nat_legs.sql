-- The NAT gateway's own ENI, split into the four legs CloudWatch also reports, per run window:
--   in_from_source      instances -> NAT        (srcaddr in VPC, dstaddr = NAT private IP)
--   out_to_destination  NAT -> outside          (srcaddr = NAT private IP, dstaddr outside the VPC)
--   in_from_destination outside -> NAT          (srcaddr outside, dstaddr = NAT private IP)
--   out_to_source       NAT -> instances        (srcaddr = NAT private IP, dstaddr in VPC)
-- Data the NAT gateway processes = in_from_source + in_from_destination.
WITH {{BASE}}
SELECT coalesce(r.run, '(between runs)') AS run,
       sum(CASE WHEN n.dstaddr = '{{NAT_IP}}' AND n.srcaddr LIKE '{{VPC_PREFIX}}%' THEN n.bytes ELSE 0 END) AS in_from_source,
       sum(CASE WHEN n.srcaddr = '{{NAT_IP}}' AND n.dstaddr NOT LIKE '{{VPC_PREFIX}}%' THEN n.bytes ELSE 0 END) AS out_to_destination,
       sum(CASE WHEN n.dstaddr = '{{NAT_IP}}' AND n.srcaddr NOT LIKE '{{VPC_PREFIX}}%' THEN n.bytes ELSE 0 END) AS in_from_destination,
       sum(CASE WHEN n.srcaddr = '{{NAT_IP}}' AND n.dstaddr LIKE '{{VPC_PREFIX}}%' THEN n.bytes ELSE 0 END) AS out_to_source,
       sum(n.bytes) AS bytes,
       count(*) AS records
FROM f n
LEFT JOIN runs r ON n."start" BETWEEN r.t0 - {{PAD}} AND r.t1 + {{PAD}}
WHERE n.interface_id = '{{NAT_ENI}}'
GROUP BY 1
ORDER BY 1
