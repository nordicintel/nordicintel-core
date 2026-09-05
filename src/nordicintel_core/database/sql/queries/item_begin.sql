INSERT INTO harvest_item (job_id, source_table_id, dataset_id)
SELECT %s, %s, %s
FROM harvest_job WHERE id = %s AND status = 'running'
RETURNING *
