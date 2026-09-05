INSERT INTO dataset_metadata (
    dataset_id, language, label, description, notes, source, start_period, end_period,
    upstream_url, comparison_marker, content_hash, last_checked_at, last_harvested_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
ON CONFLICT (dataset_id, language) DO UPDATE SET
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    notes = EXCLUDED.notes,
    source = EXCLUDED.source,
    start_period = EXCLUDED.start_period,
    end_period = EXCLUDED.end_period,
    upstream_url = EXCLUDED.upstream_url,
    comparison_marker = EXCLUDED.comparison_marker,
    content_hash = EXCLUDED.content_hash,
    last_checked_at = now(),
    last_harvested_at = now()
