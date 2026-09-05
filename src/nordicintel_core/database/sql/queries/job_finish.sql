UPDATE harvest_job SET status = %s, finished_at = now(), error = %s, owner_backend_pid = NULL
WHERE id = %s AND status = 'running' RETURNING *
