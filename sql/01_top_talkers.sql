-- Top talkers over the whole build: which ENI (instance or AWS-managed, e.g. the NAT gateway), in
-- which AZ, sent or received the most bytes, between which addresses and AWS services.
WITH {{BASE}}
SELECT interface_id,
       coalesce(nullif(instance_id, '-'), '(AWS-managed ENI)') AS owner,
       az_id,
       flow_direction,
       srcaddr,
       dstaddr,
       coalesce(nullif(pkt_src_aws_service, '-'), '-') AS src_service,
       coalesce(nullif(pkt_dst_aws_service, '-'), '-') AS dst_service,
       sum(bytes) AS bytes,
       sum(packets) AS packets
FROM f
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
ORDER BY 9 DESC
LIMIT 40
