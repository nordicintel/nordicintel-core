UPDATE harvest_job SET cancel_requested = true
WHERE id = %s AND status = 'running' RETURNING *
