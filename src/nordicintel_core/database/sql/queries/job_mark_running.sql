UPDATE harvest_job SET status = 'running', started_at = now(), heartbeat_at = now()
WHERE id = %s AND status = 'queued' RETURNING *
