SELECT d.provider_id, d.id AS table_id, d.native_table_id, m.language, m.label,
       m.description, m.notes, m.source, m.start_period, m.end_period, m.upstream_url,
       m.comparison_marker,
       COALESCE((
           SELECT jsonb_agg(jsonb_build_object(
               'code', dim.code,
               'label', dim.label,
               'ordinal', dim.ordinal,
               'role', dim.role,
               'note', dim.note,
               'categories', COALESCE((
                   SELECT jsonb_agg(jsonb_build_object(
                       'code', cat.code,
                       'label', cat.label,
                       'ordinal', cat.ordinal,
                       'note', cat.note,
                       'unit', cat.unit
                   ) ORDER BY cat.ordinal)
                   FROM category AS cat
                   WHERE cat.dataset_id = dim.dataset_id
                     AND cat.language = dim.language
                     AND cat.dimension_code = dim.code
               ), '[]'::jsonb)
           ) ORDER BY dim.ordinal)
           FROM dimension AS dim
           WHERE dim.dataset_id = d.id AND dim.language = m.language
       ), '[]'::jsonb) AS dimensions,
       COALESCE((
           SELECT jsonb_agg(alias ORDER BY alias)
           FROM dataset_alias
           WHERE dataset_id = d.id AND valid_to IS NULL
       ), '[]'::jsonb) AS aliases
FROM dataset AS d JOIN dataset_metadata AS m ON m.dataset_id = d.id
WHERE d.id = %s AND m.language = %s
