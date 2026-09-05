# Changelog

## Unreleased — breaking metadata/schema rewrite

- Implement the complete JSON-stat Dataset from scratch in `nordicintel_core.jsonstat`,
  with Pydantic types for every Dataset field and all published PxWeb extensions.
  Validate against the public specification and cube/reference consistency rules.
  Remove the external model dependency and sibling repository CI checkout.
  Metadata and live data use the same core-owned Dataset type.

- Define the schema as a SQLAlchemy declarative model (`database/schema.py`) and generate
  the Alembic revision from it. Remove the packaged `.sql` migration and query resources,
  `sql_files`, and `connect`; repositories now take a `Session`. `migrate check` compares
  the database against the model, so schema drift fails a command and a test instead of a
  query at runtime.
- Realign the repositories with the rewritten schema: write `first_period`/`last_period`/
  `href`, use `index` on dimensions and categories, and separate `dataset.retired` from the
  publisher's `dataset_metadata.discontinued`. Both are hidden from search unless
  `include_discontinued` is set.
- Add `create_api_engine`, `create_owner_engine`, `session_scope`, `owner_session` and
  `backend_pid`. Workers must hold one `NullPool` connection for a whole job: advisory
  locks and `owner_backend_pid` do not survive a swapped backend.
- Move `sqlalchemy` into the `db` extra; it is a runtime dependency, not migration-only.
- Remove `DataCube`; adapters return a metadata-bearing `Dataset` with JSON-stat
  `value` and optional sparse `status`, not aligned values/statuses arrays.
- Expand normalized metadata to the combined Table and Dataset information, with
  typed links, contacts, units and statistical extensions. Required catalogue
  publication fields are no longer silently omitted.
- Replace `ordinal` with `index`, scalar notes with arrays, and duplicated dimension
  roles with validated Dataset role references. Replace `start_period`, `end_period`
  and `upstream_url` with `first_period`, `last_period` and `href`.
- Rewrite the initial definitions to represent the models, separating retirement from
  upstream discontinuation. This is a rewritten `0001_initial`, not an additive upgrade: a
  database already stamped with the previous revision is not transformed by `upgrade head`.

## 0.1.0

- Add strict shared models for providers, harvesting, metadata, explicit selections, and live data.
- Add asynchronous adapter protocols and an injected HTTP client with bounded safe retries.
- Add the initial core-owned PostgreSQL schema and standalone migration command.
- Add typed Psycopg repositories for providers, metadata, schedules, and harvest lifecycle control.

This is the first published contract. Until 1.0, breaking model or protocol changes increment the
minor version and are called out here.
