UPDATE harvest_job SET status = %s, finished_at = now(), error = %s
WHERE id = %s AND status = 'running' RETURNING *
