-- Bytes per run window, per instance ENI, direction, route and peer. Route: same-AZ / cross-AZ for
-- peers inside the VPC (peer AZ from ipaz), otherwise the conversation's egress traffic_path:
-- 1 = through another resource in the VPC (here: the NAT gateway's ENI), 2 or 7 = gateway VPC
-- endpoint (the private subnets have no internet gateway route), 8 = internet gateway.
-- Records outside every run window land in '(between runs)': the background.
WITH {{BASE}}
SELECT coalesce(r.run, '(between runs)') AS run,
       i.interface_id,
       i.flow_direction,
       CASE
         WHEN i.peer LIKE '{{VPC_PREFIX}}%' THEN
           CASE WHEN p.az_id IS NULL THEN 'in-VPC (peer AZ unknown)'
                WHEN p.az_id = i.az_id THEN 'same-AZ'
                ELSE 'cross-AZ' END
         WHEN i.conv_path = 1 THEN 'via NAT gateway'
         WHEN i.conv_path IN (2, 7) THEN 'via gateway endpoint'
         WHEN i.conv_path = 8 THEN 'via internet gateway'
         ELSE 'outside VPC (route unknown)'
       END AS route,
       coalesce(nullif(i.peer_service, '-'), '-') AS peer_service,
       i.peer,
       i.az_id,
       coalesce(p.az_id, '-') AS peer_az,
       sum(i.bytes) AS bytes,
       sum(i.packets) AS packets,
       count(*) AS records
FROM inst i
LEFT JOIN ipaz p ON p.ip = i.peer
LEFT JOIN runs r ON i."start" BETWEEN r.t0 - {{PAD}} AND r.t1 + {{PAD}}
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
ORDER BY 1, 9 DESC
