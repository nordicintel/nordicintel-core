UPDATE dataset SET
    availability_status = 'unavailable',
    failed_languages = CASE
        WHEN %s::text IS NULL OR %s::text = ANY(failed_languages) THEN failed_languages
        ELSE array_append(failed_languages, %s::text)
    END,
    last_error = %s,
    updated_at = now()
WHERE id = %s RETURNING id
