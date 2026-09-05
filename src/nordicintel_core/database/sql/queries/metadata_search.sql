SELECT d.id AS table_id, d.provider_id, m.language, m.label, m.description,
       d.discontinued, d.operator_disabled, d.availability_status,
       ts_rank(m.search_document, websearch_to_tsquery('simple', %s)) AS rank
FROM dataset AS d JOIN dataset_metadata AS m ON m.dataset_id = d.id
WHERE m.search_document @@ websearch_to_tsquery('simple', %s)
  AND (%s::text IS NULL OR m.language = %s)
  AND (%s OR NOT d.discontinued)
  AND NOT d.operator_disabled
  AND d.availability_status = 'available'
ORDER BY rank DESC, d.id, m.language
LIMIT %s OFFSET %s
