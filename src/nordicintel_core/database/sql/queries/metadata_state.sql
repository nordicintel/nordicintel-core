SELECT m.language, m.comparison_marker, m.content_hash, m.last_checked_at, m.last_harvested_at,
       (m.language = ANY(d.failed_languages)) AS failed
FROM dataset_metadata AS m JOIN dataset AS d ON d.id = m.dataset_id
WHERE m.dataset_id = %s
ORDER BY m.language
