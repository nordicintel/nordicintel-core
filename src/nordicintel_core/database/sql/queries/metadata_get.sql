SELECT d.provider_id, d.id AS table_id, d.native_table_id, m.language, m.label,
       m.description, m.notes, m.source, m.start_period, m.end_period, m.upstream_url,
       m.comparison_marker
FROM dataset AS d JOIN dataset_metadata AS m ON m.dataset_id = d.id
WHERE d.id = %s AND m.language = %s
