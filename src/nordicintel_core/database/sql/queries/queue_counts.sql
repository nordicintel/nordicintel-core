SELECT provider_id, status, count(*) AS count
FROM harvest_job WHERE status IN ('queued', 'running')
GROUP BY provider_id, status ORDER BY provider_id, status
