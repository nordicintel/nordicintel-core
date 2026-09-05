SELECT code, label, ordinal, role, note
FROM dimension WHERE dataset_id = %s AND language = %s ORDER BY ordinal
