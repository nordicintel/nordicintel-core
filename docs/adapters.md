# Adapter integration

Adapters implement `AdapterFactory` and `NordicIntelAdapter`. Hosts resolve secrets,
initialize the shared HTTP client, and pass configuration and HTTP access to the factory.
Adapters never receive a database connection.

## Metadata

`fetch_metadata(entry, languages)` returns `list[MetadataFetchResult]`. Each result has
`provider_id`, exact `native_table_id`, `metadata: LanguageMetadata`, and an optional
opaque `comparison_marker`. Core mints/resolves the canonical Table ID during acceptance.

`LanguageMetadata` has `language`, `catalog: TableCatalogMetadata`, and
`dataset: nordicintel_model.jsonstat.JsonStatDataset`. Construct it from typed objects
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

Use `nordicintel_model.dumps` to serialize Dataset responses, preserving numeric values.
PxWeb extension interpretation and selection-aware enrichment live in model's `pxweb`
package. Enrichment filters category-keyed extension maps and preserves note/flag
association. Retaining codelist or elimination metadata does not implement aggregation.

## Discovery and HTTP

Adapters own upstream discovery, URL/query construction, authentication, native parsing,
and marker semantics. A publication timestamp is a safe skip marker only if the adapter
knows it covers relevant metadata changes.

`DiscoveryResult.authoritative` can be true only after the complete provider scope was
enumerated. Incomplete/single-table discovery must not retire unseen tables.

Retries are opt-in through `retry_safe=True` for operations known to be safe to repeat.
