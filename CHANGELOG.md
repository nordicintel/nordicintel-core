# Changelog

## Unreleased — breaking metadata/schema rewrite

- Remove `DataCube`; adapters return a metadata-bearing `Dataset` with JSON-stat
  `value` and optional sparse `status`, not aligned values/statuses arrays.
- Expand normalized metadata to the combined Table and Dataset information, with
  typed links, contacts, units and statistical extensions. Required catalogue
  publication fields are no longer silently omitted.
- Replace `ordinal` with `index`, scalar notes with arrays, and duplicated dimension
  roles with validated Dataset role references. Replace `start_period`, `end_period`
  and `upstream_url` with `first_period`, `last_period` and `href`.
- Rewrite initial SQL definitions to represent the models, separating retirement
  from upstream discontinuation. Repository/query alignment is explicitly deferred;
  this intermediate state is not a compatible database release.

## 0.1.0

- Add strict shared models for providers, harvesting, metadata, explicit selections, and live data.
- Add asynchronous adapter protocols and an injected HTTP client with bounded safe retries.
- Add the initial core-owned PostgreSQL schema and standalone migration command.
- Add typed Psycopg repositories for providers, metadata, schedules, and harvest lifecycle control.

This is the first published contract. Until 1.0, breaking model or protocol changes increment the
minor version and are called out here.
