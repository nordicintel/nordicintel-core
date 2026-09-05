SELECT * FROM harvest_job
WHERE id = %s AND owner_backend_pid = pg_backend_pid()
FOR UPDATE
