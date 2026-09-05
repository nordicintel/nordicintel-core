SELECT id FROM dataset WHERE id = %s
UNION ALL
SELECT dataset_id AS id FROM dataset_alias WHERE alias = %s AND valid_to IS NULL
LIMIT 1
