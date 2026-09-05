SELECT id, provider_id FROM harvest_job
WHERE status = 'running' AND heartbeat_at < now() - %s * interval '1 second'
ORDER BY heartbeat_at, id LIMIT %s
