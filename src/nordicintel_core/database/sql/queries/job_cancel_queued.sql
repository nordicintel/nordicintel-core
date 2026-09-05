UPDATE harvest_job SET status = 'cancelled', finished_at = now()
WHERE id = %s AND status = 'queued' RETURNING *
