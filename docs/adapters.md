# Adapter integration

Adapters implement `AdapterFactory` and `NordicIntelAdapter`. Hosts resolve secrets,
initialize the shared HTTP client, and pass configuration and HTTP access to the factory.
Adapters never receive a database connection.

## Metadata

`fetch_metadata(entry, languages)` returns `list[MetadataFetchResult]`. Each result has
`provider_id`, exact `native_table_id`, `metadata: LanguageMetadata`, and an optional
opaque `comparison_marker`. Core mints/resolves the canonical Table ID during acceptance.

`LanguageMetadata` has `language`, `catalog: TableCatalogMetadata`, and
`dataset: nordicintel_core.jsonstat.JsonStatDataset`. Construct it from typed objects
or a JSON-stat mapping. The Dataset preserves the JSON-stat/PxWeb wire structure,
including relation-keyed links, roles, category order, units, notes, and extensions.
Metadata acceptance requires an empty dense `value` array and no observation status.

Catalog fields describe the Table response. They remain distinct from similarly named
Dataset fields: differing titles or source descriptions are retained. Adapters should
diagnose inconsistencies and use provider-specific consistency checks when independently
fetched responses may span an upstream update. Never replace publisher update times
with local timestamps or silently mix incompatible structures.

Language representations are complete and independent. Core commits a language's
catalog, Dataset, search projection, and successful comparison marker together. The
marker describes accepted metadata, not a merely attempted fetch. Failed languages
retain their previous metadata and are represented in `LanguageState`, including a
language whose first fetch has failed.

## Live data

`fetch_data(native_table_id, selection)` returns the same `JsonStatDataset` type with
selected dimensions/categories, values, and optional status. The API obtains native
routing identity from `MetadataRepository.get_table(table_id)`. Selection expansion
and preflight happen before dispatch. Preserve the live Dataset's observation order;
never attach selected values positionally to the full harvested structure.

Use `nordicintel_core.jsonstat.dumps` to serialize Dataset responses, preserving numeric values.
The complete Dataset and typed PxWeb extensions live in `nordicintel_core.jsonstat`.
See [the Dataset model](jsonstat.md) for construction, validation and serialization.
Adapters that enrich selections must filter category-keyed extension maps and preserve
note/flag association. Retaining codelist or elimination metadata does not implement aggregation.

## Discovery and HTTP

Adapters own upstream discovery, URL/query construction, authentication, native parsing,
and marker semantics. A publication timestamp is a safe skip marker only if the adapter
knows it covers relevant metadata changes.

`DiscoveryResult.authoritative` can be true only after the complete provider scope was
enumerated. Incomplete/single-table discovery must not retire unseen tables, and
`reconcile_inventory` refuses a scope that names a Table for exactly that reason.

`DiscoveryScope.table_id` is canonical and an adapter cannot resolve it. When a job is
narrowed to one Table the worker resolves it first and also supplies
`DiscoveryScope.native_table_id`, so an adapter can address the Table directly rather
than enumerating a whole catalogue to filter it. Both fields are absent for a
provider-wide traversal. Never parse a canonical slug back into an upstream identifier.

Retries are opt-in through `retry_safe=True` for operations known to be safe to repeat.
