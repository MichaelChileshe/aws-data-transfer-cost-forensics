-- Shared CTEs (forensics.py puts this where a query says {{BASE}}). Placeholders in {{...}} are
-- filled from Terraform outputs and build/results/runs.jsonl; build/results/sql/ has the filled-in
-- copies that ran, ready to paste into the Athena console.
--
-- f      : this VPC's flow records in the build window (partition-pruned: only the build hours are read)
-- runs   : one row per traffic run: name, start, end (Unix seconds, instance clock)
-- ipaz   : every private IP in the VPC -> its AZ ID, learned from the flow logs themselves. On any ENI,
--          srcaddr of an EGRESS record and dstaddr of an INGRESS record are that ENI's own private IP,
--          and az_id is the AZ of the ENI that captured the record. So the peer's AZ comes from the
--          peer's OWN records (flow logs on both ENIs), not from the record being classified.
-- inst   : records captured on the instances' ENIs (instance_id set), with the peer address, the
--          peer's AWS service, and the egress route of the whole conversation (traffic_path exists
--          only on egress records; the window function copies it to the ingress records of the same
--          5-tuple so downloads get a route too).
f AS (
  SELECT interface_id, instance_id, az_id, flow_direction, traffic_path, srcaddr, dstaddr, srcport,
         dstport, protocol, packets, bytes, "start", "end", pkt_srcaddr, pkt_dstaddr,
         pkt_src_aws_service, pkt_dst_aws_service
  FROM {{TABLE}}
  WHERE {{PARTITIONS}}
    AND vpc_id = '{{VPC_ID}}'
    AND log_status = 'OK'
    AND "start" BETWEEN {{T0}} AND {{T1}}
),
runs (run, t0, t1) AS (
  VALUES {{RUNS}}
),
ipaz AS (
  SELECT ip, max(az_id) AS az_id
  FROM (SELECT CASE WHEN flow_direction = 'egress' THEN srcaddr ELSE dstaddr END AS ip, az_id FROM f) x
  WHERE ip LIKE '{{VPC_PREFIX}}%'
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
