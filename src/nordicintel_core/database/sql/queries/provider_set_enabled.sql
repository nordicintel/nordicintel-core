UPDATE provider SET enabled = %s, updated_at = now() WHERE id = %s RETURNING id
