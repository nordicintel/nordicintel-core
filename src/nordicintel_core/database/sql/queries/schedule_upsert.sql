INSERT INTO harvest_schedule (provider_id, enabled, every_seconds, next_run_at, request)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (provider_id) DO UPDATE SET
    enabled = EXCLUDED.enabled,
    every_seconds = EXCLUDED.every_seconds,
    next_run_at = EXCLUDED.next_run_at,
    request = EXCLUDED.request
RETURNING *
