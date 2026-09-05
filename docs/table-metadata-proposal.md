# Table metadata model

Implemented 2026-09-05. This supersedes the earlier flattened metadata proposal.

```text
TableRecord
  table_id, provider_id, native_table_id
  serving_mode, operator_disabled, retired, availability_status

LanguageMetadata
  language
  catalog: TableCatalogMetadata
  dataset: JsonStatDataset

TableLanguageMetadata extends LanguageMetadata
  table_id

MetadataFetchResult
  provider_id, native_table_id
  metadata: LanguageMetadata
  comparison_marker

LanguageState
  language, comparison_marker, content_hash
  last_checked_at, last_harvested_at, failed, last_error
```

## One statistical Dataset

`nordicintel-model` owns the JSON-stat 2.0 Dataset and codec. Core composes that exact
type with catalog metadata; there is no second flattened Dataset implementation.
Metadata output uses a full-domain Dataset with `value: []`. Live data uses the same
type with selected dimensions/categories, observations, and optional status.

Dimensions, category indexes, roles, units, notes, links, and extensions retain their
JSON-stat locations. PxWeb wrappers interpret known extension fields. Generic JSON-stat
validation does not assign PxWeb meaning to otherwise open extensions.

JSON-stat shape is validated against the bundled supplied schema, followed by semantic
checks for sizes, category order/references, roles, and observation indexing. Core also
validates known PxWeb category references, note indices, placement, and measurement enums.
The metadata boundary requires an empty dense value array and absent observation status.

## Table and catalog

A Table has one stable canonical ID and one unique `(provider_id, native_table_id)` pair.
Canonical IDs are minted once; changing a title does not change identity. Native codes
preserve spelling and case. Colliding readable slugs receive a deterministic suffix.
There are no alternate public identifiers or compatibility lookup paths.

Catalog metadata carries the Table response's label, description, source, updated time,
period bounds, variable names, links, sort code, tags, category, discontinued flag,
subject code, time unit, and subject paths. It stays separate from similarly named
Dataset attributes. A catalog title can differ from a Dataset title without losing either.
Publisher timestamps remain source strings, distinct from local harvest timestamps.

The native identity and controls are available through `get_table`; accepted language
metadata is available through `get_language`. Adapters receive the native ID explicitly
for live data. Adapters do not manufacture canonical IDs for newly discovered tables.

## Persistence and ownership

Core owns the SQLAlchemy schema and initial Alembic migration. The relations are
`provider`, `table_registry`, `table_metadata`, `table_language_state`, `harvest_schedule`,
`harvest_job`, and `harvest_item`.

`table_metadata` keeps catalog columns and a complete JSON-stat metadata document in
JSONB. This gives metadata readers one coherent object and removes redundant relational
copies of every dimension/category. PostgreSQL search remains a derived projection,
updated alongside the document. JSONB key order is irrelevant; JSON-stat indexes carry
semantic category order. Numeric metadata is retained as JSON numbers.

A language replacement and its successful comparison marker commit atomically. Failure
leaves its previous Dataset intact. A language's first failed fetch can have state
without fabricated metadata. Language variants retain their own structure and freshness.
Operator disabling, worker availability, source discontinuation, and discovery retirement
remain distinct. Existing queue ownership, short transactions, and retirement rules remain.

There is no deployed predecessor schema to migrate. The initial migration defines this
model directly. Neither observations nor historical metadata versions are persisted.

## Package boundaries

`nordicintel-model`: JSON-stat Dataset/value types, codec, generic validation, PxWeb DTOs,
extension interpretation, selection-aware enrichment, and CSV support.

`nordicintel-core.models`: Table identity, catalog/language envelopes, provider and adapter
contracts, explicit selections, and harvest lifecycle/state.

`nordicintel-core.database`: schema, migrations, metadata/search, configuration, and queue.
`nordicintel-core.http`: injected HTTP transport and retry/rate-limit utilities.

API and harvest services consume core. Provider-family adapters return shared Datasets.
Core now requires Python 3.12+ and declares a model-package dependency. Local uv development
uses a sibling `nordicintel-model` checkout; release wheels use a normal version requirement.

## Response discipline

Use the Dataset codec for `/metadata` and `/data` serialization. A selected response's
structure describes its actual cells. Stored metadata can enrich compatible descriptions;
it cannot replace the live response's indexing. Enrichment filters category-specific
extension maps and handles note flags alongside the corresponding notes.

Codelist references, PX presentation hints, and elimination metadata are preserved.
Their presence does not add codelist/default-selection/saved-query services or implicit
aggregation execution.

See [adapter integration](adapters.md) and [database integration](database.md) for the
implemented contracts. The schemas and supplied PxTools documentation in the model
repository remain the protocol references.
