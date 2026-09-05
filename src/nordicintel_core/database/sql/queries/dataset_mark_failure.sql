UPDATE dataset SET availability_status = 'unavailable', last_error = %s, updated_at = now()
WHERE id = %s RETURNING id
