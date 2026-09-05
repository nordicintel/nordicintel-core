UPDATE harvest_job SET heartbeat_at = now()
WHERE id = %s AND status = 'running'
RETURNING cancel_requested
