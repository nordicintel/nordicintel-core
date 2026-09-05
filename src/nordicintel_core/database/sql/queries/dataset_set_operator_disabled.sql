UPDATE dataset SET operator_disabled = %s, updated_at = now() WHERE id = %s RETURNING id
