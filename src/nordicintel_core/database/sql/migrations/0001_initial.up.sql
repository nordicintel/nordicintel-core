CREATE TABLE provider (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9._-]*$'),
    label text NOT NULL CHECK (length(label) > 0),
    description text,
    website text,
    region text CHECK (region IS NULL OR region ~ '^[A-Z]{2}$'),
    adapter_type text NOT NULL CHECK (adapter_type ~ '^[a-z0-9][a-z0-9._-]*$'),
    config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config) = 'object'),
    secret_refs jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(secret_refs) = 'object'),
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dataset (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9._-]*$'),
    provider_id text NOT NULL REFERENCES provider(id),
    native_table_id text NOT NULL CHECK (length(native_table_id) > 0),
    serving_mode text NOT NULL DEFAULT 'routed' CHECK (serving_mode IN ('routed')),
    -- Absence-based retirement is not the publisher's discontinued metadata flag.
    retired boolean NOT NULL DEFAULT false,
    operator_disabled boolean NOT NULL DEFAULT false,
    availability_status text NOT NULL DEFAULT 'available'
        CHECK (availability_status IN ('available', 'unavailable')),
    failed_languages text[] NOT NULL DEFAULT '{}'::text[],
    last_error jsonb CHECK (last_error IS NULL OR jsonb_typeof(last_error) = 'object'),
    last_harvested_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_id, native_table_id)
);

CREATE TABLE dataset_alias (
    alias text PRIMARY KEY CHECK (length(alias) > 0 AND position('/' in alias) = 0),
    dataset_id text NOT NULL REFERENCES dataset(id),
    kind text NOT NULL DEFAULT 'native',
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

-- Language-scoped union of Table and Dataset metadata. Compound typed values are
-- JSONB; ordered dimensions/categories are child relations. No observations or
-- redundant JSON-stat id/size/version/class are stored.
CREATE TABLE dataset_metadata (
    dataset_id text NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
    language text NOT NULL CHECK (length(language) > 0 AND language = lower(btrim(language))),
    label text NOT NULL CHECK (length(label) > 0),
    description text,
    sort_code text,
    tags text[],
    updated text NOT NULL CHECK (length(updated) > 0),
    first_period text NOT NULL CHECK (length(first_period) > 0),
    last_period text NOT NULL CHECK (length(last_period) > 0),
    variable_names text[] NOT NULL,
    category text CHECK (category IN ('internal', 'public', 'private', 'section')),
    discontinued boolean,
    source text,
    subject_code text,
    time_unit text CHECK (time_unit IN ('Annual', 'Quarterly', 'Monthly', 'Weekly', 'Other')),
    paths jsonb CHECK (paths IS NULL OR jsonb_typeof(paths) = 'array'),
    links jsonb NOT NULL CHECK (jsonb_typeof(links) = 'array'),
    href text,
    link jsonb CHECK (link IS NULL OR jsonb_typeof(link) = 'object'),
    notes text[],
    roles jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(roles) = 'object' AND roles - ARRAY['time', 'geo', 'metric'] = '{}'::jsonb
    ),
    note_mandatory jsonb CHECK (
        note_mandatory IS NULL OR jsonb_typeof(note_mandatory) = 'object'
    ),
    px jsonb CHECK (px IS NULL OR jsonb_typeof(px) = 'object'),
    contacts jsonb CHECK (contacts IS NULL OR jsonb_typeof(contacts) = 'array'),
    comparison_marker jsonb CHECK (
        comparison_marker IS NULL OR jsonb_typeof(comparison_marker) = 'object'
    ),
    content_hash text,
    last_checked_at timestamptz NOT NULL DEFAULT now(),
    last_harvested_at timestamptz NOT NULL DEFAULT now(),
    search_document tsvector NOT NULL DEFAULT ''::tsvector,
    PRIMARY KEY (dataset_id, language)
);

CREATE TABLE dimension (
    dataset_id text NOT NULL,
    language text NOT NULL,
    code text NOT NULL CHECK (length(btrim(code)) > 0),
    index integer NOT NULL CHECK (index >= 0),
    label text,
    notes text[],
    extension jsonb CHECK (extension IS NULL OR jsonb_typeof(extension) = 'object'),
    link jsonb CHECK (link IS NULL OR jsonb_typeof(link) = 'object'),
    PRIMARY KEY (dataset_id, language, code),
    UNIQUE (dataset_id, language, index),
    FOREIGN KEY (dataset_id, language)
        REFERENCES dataset_metadata(dataset_id, language) ON DELETE CASCADE
);

CREATE TABLE category (
    dataset_id text NOT NULL,
    language text NOT NULL,
    dimension_code text NOT NULL,
    code text NOT NULL CHECK (length(btrim(code)) > 0),
    index integer NOT NULL CHECK (index >= 0),
    label text,
    notes text[],
    child text[],
    unit jsonb CHECK (unit IS NULL OR jsonb_typeof(unit) = 'object'),
    PRIMARY KEY (dataset_id, language, dimension_code, code),
    UNIQUE (dataset_id, language, dimension_code, index),
    FOREIGN KEY (dataset_id, language, dimension_code)
        REFERENCES dimension(dataset_id, language, code) ON DELETE CASCADE
);

CREATE TABLE harvest_schedule (
    provider_id text PRIMARY KEY REFERENCES provider(id),
    enabled boolean NOT NULL DEFAULT true,
    every_seconds integer NOT NULL CHECK (every_seconds > 0),
    next_run_at timestamptz NOT NULL,
    request jsonb NOT NULL DEFAULT '{"table_id":null,"force":false,"languages":null}'::jsonb
        CHECK (jsonb_typeof(request) = 'object' AND request->'table_id' = 'null'::jsonb)
);

CREATE TABLE harvest_job (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id text NOT NULL REFERENCES provider(id),
    request jsonb NOT NULL CHECK (jsonb_typeof(request) = 'object'),
    trigger text NOT NULL DEFAULT 'manual' CHECK (trigger IN ('manual', 'schedule')),
    request_key text UNIQUE CHECK (
        request_key IS NULL OR length(request_key) BETWEEN 1 AND 200
    ),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    cancel_requested boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    heartbeat_at timestamptz,
    owner_backend_pid integer,
    finished_at timestamptz,
    error jsonb CHECK (error IS NULL OR jsonb_typeof(error) = 'object'),
    CHECK (status <> 'running' OR (
        started_at IS NOT NULL AND heartbeat_at IS NOT NULL AND owner_backend_pid IS NOT NULL
    )),
    CHECK (status NOT IN ('completed', 'failed', 'cancelled') OR finished_at IS NOT NULL),
    CHECK (status <> 'failed' OR error IS NOT NULL)
);

CREATE TABLE harvest_item (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id bigint NOT NULL REFERENCES harvest_job(id) ON DELETE CASCADE,
    source_table_id text NOT NULL CHECK (length(source_table_id) > 0),
    dataset_id text REFERENCES dataset(id),
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'updated', 'skipped', 'failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error jsonb CHECK (error IS NULL OR jsonb_typeof(error) = 'object'),
    UNIQUE (job_id, source_table_id),
    CHECK (status = 'running' OR finished_at IS NOT NULL),
    CHECK (status <> 'failed' OR error IS NOT NULL)
);

CREATE INDEX dataset_provider_idx ON dataset(provider_id, id);
CREATE INDEX dataset_metadata_search_idx ON dataset_metadata USING gin(search_document);
CREATE INDEX harvest_schedule_due_idx ON harvest_schedule(next_run_at) WHERE enabled;
CREATE INDEX harvest_job_queue_idx ON harvest_job(created_at, id) WHERE status = 'queued';
CREATE UNIQUE INDEX harvest_job_one_running_provider_idx
    ON harvest_job(provider_id) WHERE status = 'running';
CREATE INDEX harvest_job_provider_history_idx
    ON harvest_job(provider_id, created_at DESC, id DESC);
CREATE INDEX harvest_job_stale_idx ON harvest_job(heartbeat_at) WHERE status = 'running';
CREATE INDEX harvest_item_job_idx ON harvest_item(job_id, status, id);
CREATE INDEX harvest_item_dataset_idx ON harvest_item(dataset_id, started_at DESC);
