SELECT s.* FROM harvest_schedule AS s
JOIN provider AS p ON p.id = s.provider_id
WHERE s.enabled AND p.enabled AND s.next_run_at <= now()
ORDER BY s.next_run_at, s.provider_id
LIMIT %s FOR UPDATE OF s SKIP LOCKED
