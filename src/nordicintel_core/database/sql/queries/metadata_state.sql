SELECT language, comparison_marker, content_hash, last_checked_at, last_harvested_at,
       (d.availability_status = 'unavailable') AS failed
FROM dataset_metadata AS m JOIN dataset AS d ON d.id = m.dataset_id
WHERE m.dataset_id = %s
ORDER BY language
