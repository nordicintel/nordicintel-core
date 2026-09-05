INSERT INTO harvest_item (job_id, source_table_id, dataset_id)
SELECT %s, %s, %s
FROM harvest_job AS job
WHERE job.id = %s AND job.status = 'running' AND job.owner_backend_pid = pg_backend_pid()
  AND (%s::text IS NULL OR EXISTS (
      SELECT 1 FROM dataset AS d WHERE d.id = %s AND d.provider_id = job.provider_id
  ))
RETURNING *
