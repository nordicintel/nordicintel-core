# `nordicintel-core`: domain and persistence onboarding

This note is for a new contributor who needs to understand what `nordicintel-core` is responsible for in the NordicIntel workspace, especially around domain language, adapter contracts, and PostgreSQL persistence.

## How to read this note

I distinguish between:

- **Facts**: statements that the repo’s docs, code, or tests say directly.
- **Inferences**: conclusions that are not stated verbatim but appear strongly implied by the current design.

Primary sources consulted for this note include `README.md`, `CONTEXT.md`, `docs/adapters.md`, `docs/database.md`, `docs/jsonstat.md`, `docs/adr/0001-core-owns-postgres-schema.md`, `docs/adr/0002-sqlalchemy-owns-schema-and-crud.md`, and the implementation/tests under `src/nordicintel_core/` and `tests/`.

## Core’s role in the four-repo system

**Fact:** `README.md` describes this repository as “shared contracts and infrastructure for NordicIntel applications and provider adapters” and explicitly says it contains “no web service or background process of its own”.

**Fact:** Light sibling context from `../nordicintel-api/README.md`, `../nordicintel-harvest/README.md`, and `../nordicintel-adapter-pxweb2/README.md` indicates the current workspace split is:

- `nordicintel-core`: shared models, adapter protocol, JSON-stat model/codec, HTTP utilities, PostgreSQL schema/migrations/repositories
- `nordicintel-api`: public/admin API
- `nordicintel-harvest`: scheduler, worker, bootstrap commands
- `nordicintel-adapter-pxweb2`: one concrete upstream adapter implementation

**Inference:** The intended architecture is “core as contract and persistence spine; sibling repos as execution surfaces”. In other words, `nordicintel-core` defines the language and invariants that the API, harvester, and adapters are expected to share rather than reinvent.

## What this repo owns

**Fact:** The docs and code state that this repository owns all of the following:

1. **Canonical domain contracts** in `src/nordicintel_core/models/`
   - provider configuration in `src/nordicintel_core/models/provider.py`
   - adapter protocols in `src/nordicintel_core/models/adapters.py`
   - harvest lifecycle/state contracts in `src/nordicintel_core/models/harvest.py`
   - metadata and table identity contracts in `src/nordicintel_core/models/metadata.py`

2. **The JSON-stat 2.0 Dataset implementation and codec** in `src/nordicintel_core/jsonstat/`
   - especially `src/nordicintel_core/jsonstat/dataset.py`
   - plus PxWeb-specific validation in `src/nordicintel_core/jsonstat/pxweb.py`

3. **The shared PostgreSQL schema and migration history** in `src/nordicintel_core/database/`
   - declarative schema in `src/nordicintel_core/database/schema.py`
   - migration CLI in `src/nordicintel_core/database/migration_cli.py`
   - Alembic history under `src/nordicintel_core/database/migrations/`

4. **Repository implementations for persistence behavior**
   - metadata/search in `src/nordicintel_core/database/metadata.py`
   - provider persistence in `src/nordicintel_core/database/providers.py`
   - queue/scheduling/job lifecycle in `src/nordicintel_core/database/queue.py`

5. **Shared database engine/session construction rules** in `src/nordicintel_core/database/engine.py`

6. **The optional shared async HTTP transport** under `src/nordicintel_core/http/`, as also summarized by `README.md` and `../nordicintel-harvest/README.md`

## What this repo explicitly does not own

**Fact:** The repo is explicit about several non-responsibilities:

- No API service or worker process lives here (`README.md`).
- Importing `nordicintel_core` must not read environment variables, open a database connection, or create an HTTP client (`README.md`, `tests/test_package.py`).
- Adapters do **not** receive a database connection (`docs/adapters.md`, `src/nordicintel_core/models/adapters.py`).
- Applications and workers do **not** run migrations automatically on startup; migrations are a separate deployment task (`docs/database.md`, `docs/adr/0001-core-owns-postgres-schema.md`, `docs/adr/0002-sqlalchemy-owns-schema-and-crud.md`).
- The repo does **not** persist live observations or historical versions of metadata; `docs/table-metadata-proposal.md` and `docs/database.md` both describe stored metadata as metadata-only JSON-stat with `value: []`.
- There is **no** alternate identifier registry; a table has one canonical ID and one `(provider_id, native_table_id)` pair (`README.md`, `docs/table-metadata-proposal.md`, `src/nordicintel_core/database/metadata.py`).
- The system intentionally does **not** infer meaning from a table’s absence in later discovery runs (`CONTEXT.md`, `docs/adapters.md`, `docs/database.md`, `src/nordicintel_core/database/schema.py`, `tests/test_postgres.py`).

**Inference:** The design tries hard to keep “transport/process concerns” and “shared invariants” separate. That makes `nordicintel-core` a dependency of the sibling repos, but not a host application in its own right.

## Canonical domain vocabulary downstream repos should respect

**Fact:** `CONTEXT.md` is the clearest canonical glossary. Downstream repos should reuse its terms rather than invent near-synonyms.

| Canonical term | The code/doc states | Avoid / caution |
| --- | --- | --- |
| **Provider** | An upstream statistical publisher configured through one adapter | Avoid “source”, “backend” |
| **Table** | A stable, addressable PxAPI catalogue resource that has metadata and can provide data | Avoid confusion with a PostgreSQL table |
| **Dataset** | The JSON-stat representation for metadata or live observations | Avoid “snapshot”, “stored observations” |
| **Adapter** | A provider-family integration | Avoid treating the adapter itself as the provider or harvester |
| **Discovery** | Enumeration of tables in exactly one language | Avoid calling it “harvest” |
| **Harvest Job** | One requested traversal of one provider or one table in one language | Avoid vague terms like “run” or “attempt” |
| **Harvest Item** | Processing outcome for one upstream table within a harvest job | Avoid “task” or “queue item” if you mean the domain object |
| **Language Metadata** | One language-specific catalog+dataset representation of a table | Avoid “translation” if you mean the whole language-specific publication |

**Fact:** `src/nordicintel_core/models/harvest.py` reinforces an important semantic rule: a harvest request always names exactly one language, because catalogues are published per language and are not assumed to be equivalent.

**Inference:** If downstream repos start using “table” to mean a database row, or “dataset” to mean only stored metadata, they will drift away from the actual shared model and eventually make persistence or API behavior confusing.

## Adapter protocol at a high level

**Fact:** The public adapter protocol is defined structurally in `src/nordicintel_core/models/adapters.py`.

A host supplies:

- `ProviderDefinition`
- resolved secrets
- a shared `AsyncHttpClient`

An adapter returns/implements:

- `supported_languages()`
- `discover(scope)`
- `should_refresh(entry, stored, force=...)`
- `fetch_metadata(entry, language)`
- `fetch_data(native_table_id, selection)`

**Fact:** `docs/adapters.md` and the protocol docstrings make several boundaries explicit:

- adapters own upstream discovery, request construction, parsing, authentication, and marker semantics
- adapters do not mint canonical table IDs; core does that during acceptance
- adapters do not decide what a missing table means globally
- one `fetch_metadata` call returns one table in one language; failures are raised, not encoded as “missing list elements”
- `should_refresh` is adapter-owned because only the adapter understands its own comparison marker semantics

**Inference:** Core wants adapters to be thin-but-authoritative translators of upstream behavior, while keeping identity, storage, and operational policy in core.

## JSON-stat model at a high level

**Fact:** `docs/jsonstat.md` and `src/nordicintel_core/jsonstat/dataset.py` say that `nordicintel-core` implements its own complete JSON-stat 2.0 Dataset model; it does not depend on a separate statistics-model package.

**Fact:** The same `JsonStatDataset` type is used for both:

- metadata datasets, which must have `value: []` and no observation `status`
- live data datasets, which can contain selected observations and optional status

**Fact:** Validation is more than shape-checking:

- wire format is validated against the bundled schema
- cube semantics are validated (dimension identity, sizes, roles, positions, hierarchy cycles, etc.)
- PxWeb-specific note/category/reference semantics are validated at the metadata boundary

**Fact:** The tests in `tests/test_jsonstat.py` and `tests/test_models.py` demonstrate that:

- Decimal values are preserved as JSON numbers
- note repetition is deliberately allowed for PxWeb note/index semantics
- category order comes from JSON-stat index semantics, not incidental map order
- nested structures are revalidated at output/persistence boundaries

**Inference:** JSON-stat is not a convenience serialization detail here; it is part of the core domain contract. If a downstream repo tries to flatten, partially copy, or casually mutate dataset structures, it will likely violate an invariant this repo assumes.

## Database schema ownership and repository boundaries

**Fact:** `docs/database.md`, `docs/adr/0002-sqlalchemy-owns-schema-and-crud.md`, and `src/nordicintel_core/database/schema.py` all align on the core rule: `src/nordicintel_core/database/schema.py` is the one authoritative schema definition.

That matters because:

- Alembic revisions are generated from `Base.metadata`
- repositories build from the same definitions
- `tests/test_schema.py` treats model-vs-migration drift as a failure

**Fact:** The current main tables are:

- `provider`
- `table_registry`
- `table_metadata`
- `table_language_state`
- `harvest_schedule`
- `harvest_job`
- `harvest_item`

**Fact:** Repository boundaries are intentionally strict:

- ORM entities stay inside `src/nordicintel_core/database/`
- callers receive Pydantic application models from `src/nordicintel_core/models/`
- metadata persistence/search is handled by `MetadataRepository`
- provider rows are handled by `ProviderRepository`
- queue/scheduling/job lifecycle is handled by `HarvestRepository` and `ScheduleRepository`

**Fact:** `table_registry` owns canonical/native identity and operational controls; `table_metadata` owns one language’s full metadata document and catalog fields; `table_language_state` owns per-language freshness/error state.

**Fact:** `docs/database.md` and `tests/test_postgres.py` are explicit that absence is not stored as retirement. A table that disappears from a later discovery run remains accepted and searchable until some future design introduces a deliberate absence policy.

**Inference:** The repository split is there to protect invariants, not just to organize files. If consumers bypass repositories or start treating ORM rows as public objects, they weaken the very boundary this repo is trying to enforce.

## Engine/session rules and why they matter

**Fact:** `src/nordicintel_core/database/engine.py`, `docs/database.md`, and `tests/test_postgres.py` describe two different engine/session modes:

- `create_api_engine()` + `session_scope()` for pooled, short-lived, request-style work
- `create_owner_engine()` + `owner_session()` for harvest ownership, pinned to one physical backend

**Fact:** Three persistence rules are emphasized repeatedly and backed by tests:

1. **One backend per job**
   - enforced through `harvest_job.owner_backend_pid` and advisory locks
   - protected by using `NullPool` for owner engines
2. **One transaction per repository call**
   - repository methods open a short `session.begin()` block and leave no transaction open
3. **Explicit worker-owned columns on harvest writes**
   - harvest paths do not load arbitrary entities and flush them back wholesale

**Why this matters:**

- if a worker silently switches database backends mid-job, ownership and advisory locking become invalid
- if a transaction stays open while waiting on upstream HTTP, a backend idles in transaction and holds locks longer than intended
- if a harvest flush overwrites full entities, it can stomp on operator decisions such as `operator_disabled`

**Inference:** These rules are the heart of the operational safety model. They look fussy on first read, but the tests suggest they exist because earlier, more convenient designs were too easy to get subtly wrong.

## Source files and tests to read first

If you only read a handful of files, start here:

1. `CONTEXT.md`
   - fastest way to learn the canonical vocabulary
2. `README.md`
   - concise statement of repo role and packaging boundaries
3. `src/nordicintel_core/models/metadata.py`
   - identity, catalog, language metadata, and acceptance boundary
4. `src/nordicintel_core/models/adapters.py`
   - the adapter contract every concrete adapter must satisfy
5. `src/nordicintel_core/jsonstat/dataset.py`
   - the real shared Dataset model and validation center
6. `src/nordicintel_core/database/schema.py`
   - what is actually persisted and how ownership is divided across tables
7. `src/nordicintel_core/database/metadata.py`
   - canonical ID minting, metadata upsert, search visibility rules, failure handling
8. `src/nordicintel_core/database/queue.py`
   - ownership, locking, scheduling, cancellation, recovery

Then read these tests, in roughly this order:

1. `tests/test_models.py`
   - compact proof of the metadata/domain contracts
2. `tests/test_jsonstat.py`
   - edge cases and invariants of the Dataset model
3. `tests/test_postgres.py`
   - the best executable explanation of persistence and ownership behavior
4. `tests/test_schema.py`
   - why schema drift is treated as a release-blocking problem
5. `tests/test_package.py`
   - packaging/import guarantees and migration asset expectations

## Open questions and documentation gaps noticed

1. **Discontinued-table default behavior is documented inconsistently.**  
   - `docs/database.md` and `tests/test_postgres.py` say discontinued tables stay visible/searchable by default, unless `include_discontinued=False`.  
   - The final consequence bullet in `docs/adr/0002-sqlalchemy-owns-schema-and-crud.md` says discontinued/retired things are hidden from search unless `include_discontinued` is set.  
   - The implementation in `src/nordicintel_core/database/metadata.py` matches `docs/database.md`, not that ADR bullet.

2. **`docs/table-metadata-proposal.md` appears partially stale.**  
   - It says “Implemented 2026-09-05”, but still includes `retired` in `TableRecord`.  
   - `src/nordicintel_core/database/schema.py` and `tests/test_schema.py` explicitly say retirement/absence is not stored anywhere.

3. **The repo explains the persistence model better than it explains the API-facing read model.**  
   - The search/catalog behavior is implemented clearly in `src/nordicintel_core/database/metadata.py`, but there is not yet a small “how API consumers should think about catalog vs search vs get_language/get_table” guide.

4. **The migration policy is clear, but the contributor workflow could be even clearer.**  
   - `docs/database.md` explains that autogenerated revisions must be reviewed because `CHECK` constraints are tricky.  
   - A short maintainer checklist for “schema change steps” would likely help future contributors avoid missing the migration/test loop.

## Bottom line

**Fact:** This repository is the shared contract layer for NordicIntel’s domain language, adapter boundary, JSON-stat semantics, and PostgreSQL persistence.

**Inference:** If you preserve the vocabulary in `CONTEXT.md`, keep adapter/database responsibilities separate, and treat the tests in `tests/test_postgres.py` and `tests/test_schema.py` as executable architecture, you will usually be working with the grain of the codebase rather than against it.
