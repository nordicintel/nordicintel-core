# JSON-stat Dataset model

`nordicintel_core.jsonstat` implements the complete JSON-stat 2.0 Dataset structure
as Pydantic models written in this repository. It has no dependency on a separate
statistical modelling package.

## Public types

| Type | Modelled content |
| --- | --- |
| `JsonStatDataset` | Version, class, ordered dimension IDs and sizes, dimensions, dense/sparse values, scalar/dense/sparse status, roles, label, source, update, notes, URI, links, errors, extension |
| `Dimension` | Category, label, URI, notes, links, extension |
| `Category` | Ordered array or position-map index, labels, notes, units, coordinates, hierarchy |
| `Unit` | Label, decimals, symbol, symbol position, base and open provider properties |
| `Role` | Time, geography and metric dimension references |
| `Link` | Every standard link field, including recursive links and optional embedded dimensions, categories, roles, values and status |
| `DatasetExtension` | Mandatory notes, PX properties, period bounds, tags, discontinuation, contacts |
| `DimensionExtension` | Elimination, elimination category, mandatory dimension/category notes, reference periods, display hint, codelists, measuring/price/adjustment types, base periods, alternative text |
| `PxProperties` | All 19 published PX root properties, including heading/stub, publication and presentation information |
| `Contact`, `CodelistInformation`, `CatalogLink`, `LinkExtension` | Typed referenced metadata and relation details |

Names follow the wire structure: `dataset.dimension["region"].category.index`,
`dataset.value` and `dataset.status`. Python attributes use underscores only where
needed for reserved or non-Python wire names; `to_mapping()` restores the exact wire
names, including `class`, `noteMandatory` and `official-statistics`.

Extension objects preserve unknown JSON properties. Their documented PxWeb fields
are typed. Unit objects also preserve provider-specific properties. Other objects
reject unknown properties according to the published JSON-stat schema.

## Construction and responses

```python
from nordicintel_core.jsonstat import JsonStatDataset, dumps, loads

metadata = JsonStatDataset.from_mapping({
    "version": "2.0",
    "class": "dataset",
    "id": ["year"],
    "size": [2],
    "dimension": {"year": {"category": {"index": ["2024", "2025"]}}},
    "value": [],
})
data = JsonStatDataset.from_mapping({**metadata.to_mapping(), "value": [10, None]})
response_body = dumps(data)
assert loads(response_body).to_mapping() == data.to_mapping()
```

The same Dataset type serves metadata and live data. Values support JSON numbers,
strings and missing values. Dense order follows `id` and each category index; sparse
keys are zero-based flat cell positions. Status supports a shared string, a dense
array with nulls, or a sparse string map.

Use `loads`/`dumps` for HTTP Dataset documents. They preserve Decimal precision as
JSON numbers, including numeric metadata, and reject non-finite numbers. Pydantic's
ordinary JSON serialization uses its own Decimal representation; it is not the
Dataset response codec. Python `to_mapping()` preserves numeric types and omitted
optional fields. Models expose the complete Pydantic JSON schema.

## Validation

Construction checks both the bundled public JSON-stat schema and cube semantics:
dimension identity, rank, sizes, contiguous category positions, category references,
acyclic hierarchies, roles, observation cardinality and sparse positions. A singleton
category can omit its index when its label supplies the code. Empty dense values
are valid metadata; a populated dense array must cover the cube.

The separate `validate_pxweb_dataset` function in `jsonstat.pxweb` checks category,
note and heading/stub references in typed PxWeb extensions. `LanguageMetadata`
applies these checks and requires `value: []` with no observation status.

Nested containers are mutable. The Dataset codec and metadata acceptance boundary
revalidate them, so an in-place edit cannot bypass validation when serving or
persisting a Dataset. Construct a replacement through `from_mapping()` when changing
the selected structure; Pydantic's `model_copy(update=...)` does not validate updates.

## Specification references and tests

The reference schemas were fetched directly from their publishers on 2026-09-05:

- [JSON-stat full specification](https://json-stat.org/full/)
- [JSON-stat Dataset schema](https://json-stat.org/format/schema/2.0/dataset.json)
- [PxWeb OpenAPI specification](https://data.ssb.no/api/pxwebapi/v2/swagger/v2/swagger.json)

Snapshots are in `docs/references`; the Dataset schema is also packaged for runtime
validation. Tests compare model fields with those snapshots and exercise complete
document round trips, typed extensions, invalid structures, and PostgreSQL persistence.
