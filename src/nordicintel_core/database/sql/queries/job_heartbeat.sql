UPDATE harvest_job AS job SET
    heartbeat_at = now(),
    cancel_requested = job.cancel_requested OR NOT provider.enabled
FROM provider
WHERE job.id = %s AND job.status = 'running'
  AND job.owner_backend_pid = pg_backend_pid() AND provider.id = job.provider_id
RETURNING job.cancel_requested AS stop_requested
