SELECT * FROM harvest_job
WHERE (%s::text IS NULL OR provider_id = %s)
  AND (%s::text IS NULL OR status = %s)
ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s
