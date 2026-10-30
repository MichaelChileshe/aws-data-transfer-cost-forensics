-- Did the flow logs arrive, and where? One row per hour partition: records, ENIs seen, the time the
-- last record ends, and one file path ("$path" shows the Hive-compatible layout Athena read).
SELECT "year", "month", "day", "hour",
       count(*) AS records,
       count(DISTINCT interface_id) AS enis,
       min("start") AS first_start,
       max("end") AS last_end,
       sum(bytes) AS bytes,
       min("$path") AS sample_file
FROM mvela_xfer.vpc_flow_logs
WHERE (("year" = '2026' AND "month" = '10' AND "day" = '30' AND "hour" BETWEEN '11' AND '12'))
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, 3, 4

