UPDATE harvest_item AS item SET
    status = %s, finished_at = now(), error = %s,
    dataset_id = COALESCE(%s, item.dataset_id)
FROM harvest_job AS job
WHERE item.id = %s AND item.job_id = %s AND item.status = 'running'
  AND job.id = item.job_id AND job.status = 'running'
  AND job.owner_backend_pid = pg_backend_pid()
  AND (%s::text IS NULL OR EXISTS (
      SELECT 1 FROM dataset AS d WHERE d.id = %s AND d.provider_id = job.provider_id
  ))
RETURNING item.*
