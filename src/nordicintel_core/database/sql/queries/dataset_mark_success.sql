UPDATE dataset SET
    availability_status = 'available', last_error = NULL, discontinued = false,
    last_harvested_at = now(), updated_at = now()
WHERE id = %s
