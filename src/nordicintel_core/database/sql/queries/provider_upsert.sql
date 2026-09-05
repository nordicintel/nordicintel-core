INSERT INTO provider (
    id, label, description, website, region, adapter_type, config, secret_refs, enabled
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    website = EXCLUDED.website,
    region = EXCLUDED.region,
    adapter_type = EXCLUDED.adapter_type,
    config = EXCLUDED.config,
    secret_refs = EXCLUDED.secret_refs,
    enabled = EXCLUDED.enabled,
    updated_at = now()
RETURNING id, label, description, website, region, adapter_type, config, secret_refs, enabled
