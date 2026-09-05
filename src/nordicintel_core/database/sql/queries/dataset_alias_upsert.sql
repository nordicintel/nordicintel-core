INSERT INTO dataset_alias (alias, dataset_id, kind)
SELECT %s, %s, %s
WHERE NOT EXISTS (SELECT 1 FROM dataset WHERE id = %s)
ON CONFLICT (alias) DO UPDATE SET
    dataset_id = EXCLUDED.dataset_id,
    kind = EXCLUDED.kind,
    valid_to = NULL
WHERE dataset_alias.dataset_id = EXCLUDED.dataset_id
RETURNING alias
