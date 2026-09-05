UPDATE dataset SET discontinued = true, updated_at = now()
WHERE provider_id = %s AND NOT (native_table_id = ANY(%s::text[]))
RETURNING id
