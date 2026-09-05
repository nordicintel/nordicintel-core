SELECT 1 FROM harvest_job WHERE provider_id = %s AND status IN ('queued', 'running') LIMIT 1
