SELECT j.* FROM harvest_job AS j JOIN provider AS p ON p.id = j.provider_id
WHERE j.status = 'queued' AND p.enabled
  AND NOT (j.provider_id = ANY(%s::text[]))
  AND NOT EXISTS (
      SELECT 1 FROM harvest_job AS active
      WHERE active.provider_id = j.provider_id AND active.status = 'running'
  )
ORDER BY j.created_at, j.id
LIMIT 1 FOR UPDATE OF j SKIP LOCKED
