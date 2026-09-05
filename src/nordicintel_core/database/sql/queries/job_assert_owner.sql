SELECT job.provider_id
FROM harvest_job AS job JOIN provider ON provider.id = job.provider_id
WHERE job.id = %s AND job.status = 'running'
  AND job.owner_backend_pid = pg_backend_pid()
  AND NOT job.cancel_requested AND provider.enabled
