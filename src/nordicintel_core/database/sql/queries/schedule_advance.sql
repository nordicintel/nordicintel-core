UPDATE harvest_schedule
SET next_run_at = now() + every_seconds * interval '1 second'
WHERE provider_id = %s
