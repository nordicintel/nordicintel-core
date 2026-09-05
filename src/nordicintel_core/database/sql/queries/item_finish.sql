UPDATE harvest_item AS item SET
    status = %s, finished_at = now(), error = %s,
    dataset_id = COALESCE(%s, item.dataset_id)
FROM harvest_job AS job
WHERE item.id = %s AND item.job_id = %s AND item.status = 'running'
  AND job.id = item.job_id AND job.status = 'running'
RETURNING item.*
