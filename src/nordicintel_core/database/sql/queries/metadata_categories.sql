SELECT dimension_code, code, label, ordinal, note, unit
FROM category WHERE dataset_id = %s AND language = %s
ORDER BY dimension_code, ordinal
