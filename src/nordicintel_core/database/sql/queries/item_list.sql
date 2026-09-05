SELECT * FROM harvest_item
WHERE job_id = %s AND (%s::text IS NULL OR status = %s)
ORDER BY id LIMIT %s OFFSET %s
