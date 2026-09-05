UPDATE harvest_item SET status = 'failed', finished_at = now(), error = %s
WHERE job_id = %s AND status = 'running'
