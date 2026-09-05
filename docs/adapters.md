# Adapter integration

An adapter package implements `AdapterFactory` and `NordicIntelAdapter` from
`nordicintel_core.models`. The host resolves secret references, owns an `httpx.AsyncClient`, wraps it
in `nordicintel_core.http.HttpClient`, and injects both configuration and HTTP access into the
factory.

Adapters own provider-specific URLs, authentication, discovery, request construction, response
parsing, and comparison-marker semantics. They return normalized core models and never receive a
database connection. Live-data requests always contain explicit category codes; expression parsing
and selection expansion happen before adapter dispatch.

## Metadata contract

`NormalizedTableMetadata` contains the combined information from PxWebApi2's
`TableResponse` (`GET tables/{id}`) and `Dataset` (`GET tables/{id}/metadata`). It is
not a subset chosen to suit the database. Names are normalized to snake_case; API
response serialization remains the API's responsibility.

| Upstream information | Normalized location |
| --- | --- |
| Table `id` | `native_table_id`; `table_id` is the NordicIntel canonical identity |
| Table `language`, `label`, `description`, `sortCode`, `tags`, `updated` | `language`, `label`, `description`, `sort_code`, `tags`, `updated` |
| Table `firstPeriod`, `lastPeriod`, `category`, `variableNames`, `discontinued` | `first_period`, `last_period`, `category`, `variable_names`, `discontinued` |
| Table `source`, `subjectCode`, `timeUnit`, `paths`, `links` | `source`, `subject_code`, `time_unit`, typed `paths` and `links` |
| Dataset `label`, `source`, `updated` | Shared `label`, `source`, `updated` |
| Dataset `href`, `link`, `note`, `role`, `dimension` | `href`, typed `link`, `notes`, `roles`, ordered `dimensions` |
| Dataset `extension.firstPeriod`, `lastPeriod`, `tags`, `discontinued` | Shared `first_period`, `last_period`, `tags`, `discontinued` |
| Dataset `extension.noteMandatory`, `contact`, `px` | `note_mandatory`, typed `contacts`, typed `px` |
| Dataset `id`, `size` | Derived from ordered dimension codes and category counts; no stored fields |
| Dataset `version`, `class` | Wire constants `2.0`, `dataset`; no stored fields |
| Dataset `value`, `status` | Live `Dataset` only; never harvested or persisted |

Dimension/category `index` is zero-based and contiguous; lists must arrive in index
order. Category labels may be absent. Notes remain arrays at all three levels.
Category `child` preserves hierarchy, and `unit` has typed `base` and `decimals`.
Dimension `link` and every field of `ExtensionDimension` are retained in typed
objects, including elimination, mandatory notes, reference/base periods,
measurement/price/adjustment types, alternative text, and codelist references.
References do not implement codelist storage or endpoints.

The complete `extension.px` information is retained separately, including its native
table identifier, language, contents, description, placement, publication flags,
subject details, next update, survey and update frequency. These are not assumed to
equal similarly named catalogue fields. `variable_names` is likewise retained:
the upstream schema does not guarantee equality with dimension labels.

Adapters reconcile shared Table/Dataset attributes before constructing the combined
model. Conflicting non-null values must be treated as a normalization error rather
than silently discarding one. `updated` retains the upstream string: the supplied
specification inconsistently declares a date-only pattern and a date-time format.
It must not be substituted with a local harvest timestamp.

`fetch_data` returns `Dataset`, with the same Dataset metadata and a `value` array.
`status` is optional and sparse, keyed by zero-based cell index. A metadata Dataset
has an empty `value` array; it does not need fabricated observations or statuses.
There is no separate cube abstraction or redundant `id`/`size` input contract.

`DiscoveryResult.authoritative` may be true only when its provider-wide scope was completely
enumerated. Core rejects absence-based retirement for incomplete or single-table discovery.

HTTP retries are opt-in per operation. An adapter may mark a GET or a read-only POST as
`retry_safe=True`; mutating or ambiguous operations must keep the default.
