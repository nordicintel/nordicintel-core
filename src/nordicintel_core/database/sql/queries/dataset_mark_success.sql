UPDATE dataset SET
    availability_status = CASE
        WHEN cardinality(array_remove(failed_languages, %s)) = 0 THEN 'available'
        ELSE 'unavailable'
    END,
    failed_languages = array_remove(failed_languages, %s),
    last_error = CASE
        WHEN cardinality(array_remove(failed_languages, %s)) = 0 THEN NULL
        ELSE last_error
    END,
    discontinued = false,
    last_harvested_at = now(), updated_at = now()
WHERE id = %s
