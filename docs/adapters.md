# Adapter integration

Adapters implement `AdapterFactory` and `NordicIntelAdapter`. Hosts resolve secrets,
initialize the shared HTTP client, and pass configuration and HTTP access to the factory.
Adapters never receive a database connection.

## Metadata

`fetch_metadata(entry, language)` returns one `MetadataFetchResult`, with `provider_id`,
exact `native_table_id`, `metadata: LanguageMetadata`, and an optional opaque
`comparison_marker`. One call, one language, one result: failure is raised rather than
represented as a missing element of a returned list, so a caller never has to decide what
an absent result was supposed to mean. Core mints/resolves the canonical Table ID during
acceptance.

`should_refresh(entry, stored, force=...)` decides whether that fetch is needed at all.
`stored` is the `LanguageState` core holds for this Table in this language, or None if it
has never been accepted. Only the adapter knows what its own marker means, so only the
adapter answers it.

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

`DiscoveryScope.language` is required, and is the language the enumeration is *in* rather
than a filter over it. Catalogues are published per language: a Table never published in
English is absent from the English listing, and asking for it in English is an upstream
error rather than an empty result. Listing in the scope's own language therefore makes
"can this Table be fetched in this language" a fact about the response instead of
something the host has to infer per Table.

Nothing acts on a Table's absence, so a `DiscoveryResult` makes no claim about
completeness. Report the Tables that are there.

`DiscoveryScope.table_id` is canonical and an adapter cannot resolve it. When a job is
narrowed to one Table the worker resolves it first and also supplies
`DiscoveryScope.native_table_id`, so an adapter can address the Table directly rather
than enumerating a whole catalogue to filter it. Both fields are absent for a
provider-wide traversal. Never parse a canonical slug back into an upstream identifier.

Retries are opt-in through `retry_safe=True` for operations known to be safe to repeat.
