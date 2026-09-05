UPDATE dataset_metadata SET last_checked_at = now()
WHERE dataset_id = %s AND language = %s RETURNING dataset_id
