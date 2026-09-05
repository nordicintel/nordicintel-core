INSERT INTO dataset (id, provider_id, native_table_id)
SELECT %s, %s, %s
WHERE NOT EXISTS (SELECT 1 FROM dataset_alias WHERE alias = %s)
ON CONFLICT DO NOTHING
RETURNING id
