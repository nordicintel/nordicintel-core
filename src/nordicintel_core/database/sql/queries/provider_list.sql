SELECT id, label, description, website, region, adapter_type, config, secret_refs, enabled
FROM provider ORDER BY id LIMIT %s OFFSET %s
