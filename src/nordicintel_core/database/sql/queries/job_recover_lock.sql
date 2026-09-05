SELECT id FROM harvest_job
WHERE id = %s AND status = 'running'
  AND heartbeat_at < now() - %s * interval '1 second'
FOR UPDATE
