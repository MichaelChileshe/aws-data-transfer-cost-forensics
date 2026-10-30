-- The IP -> AZ map the other queries learn from the flow logs (compared with Terraform's own view).
WITH {{BASE}}
SELECT ip, az_id FROM ipaz ORDER BY ip
