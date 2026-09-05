UPDATE harvest_job SET status = 'running', started_at = now(), heartbeat_at = now(),
    owner_backend_pid = pg_backend_pid()
WHERE id = %s AND status = 'queued' RETURNING *
