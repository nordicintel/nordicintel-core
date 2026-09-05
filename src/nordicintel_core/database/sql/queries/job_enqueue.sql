INSERT INTO harvest_job (provider_id, request, trigger, request_key)
VALUES (%s, %s, %s, %s)
ON CONFLICT (request_key) DO NOTHING
RETURNING *
