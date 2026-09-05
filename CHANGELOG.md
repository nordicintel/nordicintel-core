# Changelog

## Unreleased — breaking metadata/schema rewrite

- **A harvest run is one Provider in one language.** `HarvestRequest.language` and
  `DiscoveryScope.language` are required scalars, replacing the optional language *set*.
  A catalogue is published per language, and a Table carried in Swedish and not in English
  is absent from the English catalogue rather than empty in it — so a run over several
  languages had to decide, per Table, which languages that Table actually had. No request
  could answer that and no adapter could be asked without inventing a signal for it.
  Naming the language removes the question instead of answering it: discovery enumerates
  one language, and every Table it returns can be fetched in it as a matter of fact.
- Adapter protocol, accordingly: `resolve_languages` becomes `supported_languages`,
  `languages_to_refresh(entry, stored, requested, force=...) -> list[str]` becomes
  `should_refresh(entry, stored, force=...) -> bool`, and
  `fetch_metadata(entry, languages) -> list[...]` becomes
  `fetch_metadata(entry, language) -> MetadataFetchResult`. The list return had no way to
  express a partial failure, so an empty or short result was ambiguous by construction.
- `DiscoveryEntry.available_languages` is removed. Membership of a language's enumeration
  is the whole of that statement.
- `harvest_job` and `harvest_schedule` carry a `language` column, and a schedule is keyed
  by `(provider_id, language)`. Admission and `enqueue_due` treat a Provider as busy per
  language: two languages are different work, and folding them together starved whichever
  one lost the tie.
- **Absence handling is removed.** `TableRecord.retired`, `DiscoveryResult.authoritative`,
  `InventoryReconciliation` and `MetadataRepository.reconcile_inventory` are all gone. A
  Table missing from a later run is now left exactly as it was and stays served. Deciding
  what a disappearance means is worth doing deliberately; the mechanism as it stood turned
  ordinary per-language catalogue differences into silent data loss.
- `MetadataRepository.search` returns discontinued Tables by default
  (`include_discontinued=True`). A series the publisher has finished is still real, still
  harvested and still the right answer to a search for it. `discontinued` itself is
  unchanged: a publisher-owned attribute, stored as harvested and never inferred.
- `list_jobs` gains a `language` filter and `list_schedules` a `provider_id` filter.
- `0001_initial` is regenerated from the model. Nothing is deployed, so this is a
  replacement rather than an upgrade path.

- Add `MetadataRepository.get_table_by_native()`. Discovery yields upstream identifiers,
  and `canonical_slug` is a minting rule rather than a lookup: a collision appends a
  suffix, so a rebuilt slug can address a different Table or none.
- Replace `MetadataRepository.retire_unseen()` with `reconcile_inventory()`, which
  decides `retired` in both directions from one authoritative provider-wide discovery and
  reports the Tables it changed. Acceptance could not clear retirement, because an
  unchanged Table is skipped rather than accepted, so a Table that reappeared stayed
  retired until its content next changed. Publisher `discontinued` and operator controls
  are still never inferred from presence.
- Make `finish_job()` decide the terminal status under the job row lock instead of
  requiring the caller to have predicted it. A cancellation observed at that instant
  outranks normal completion, a genuine failure keeps its status and diagnostic, and
  items still running are closed as failed with the reason the job ended. Reporting
  completion with items still running remains a caller defect.
- Add `HarvestRepository.cancel_provider_jobs()` so disabling a Provider can also empty
  its queue and ask its running job to stop. `set_enabled(False)` still changes only the
  Provider row; running jobs stop cooperatively either way.
- Add optional `DiscoveryScope.native_table_id`, set alongside the canonical `table_id`
  when a job is narrowed to one Table, so an adapter can address it directly instead of
  enumerating a catalogue to filter it.

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
