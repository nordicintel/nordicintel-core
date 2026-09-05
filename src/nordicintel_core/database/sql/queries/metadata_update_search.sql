UPDATE dataset_metadata AS m SET search_document = to_tsvector(
    'simple',
    concat_ws(' ', m.label, m.description, m.source,
        (SELECT string_agg(d.label, ' ' ORDER BY d.ordinal)
         FROM dimension AS d
         WHERE d.dataset_id = m.dataset_id AND d.language = m.language),
        (SELECT string_agg(c.label, ' ' ORDER BY d.ordinal, c.ordinal)
         FROM category AS c JOIN dimension AS d
           ON d.dataset_id = c.dataset_id AND d.language = c.language
          AND d.code = c.dimension_code
         WHERE c.dataset_id = m.dataset_id AND c.language = m.language)
    )
)
WHERE m.dataset_id = %s AND m.language = %s
