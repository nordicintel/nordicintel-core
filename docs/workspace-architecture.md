# NordicIntel workspace architecture

This document is the quickest durable map for a newcomer to the four-repo NordicIntel workspace. It explains what each repository owns, where the main boundaries are, how metadata flows from providers into storage, and what is implemented today versus still planned.

For repo-local detail, continue into `CONTEXT.md`, `docs/adapters.md`, `docs/database.md`, `docs/onboarding/harvest-runtime.md`, `docs/onboarding/adapter-contract.md`, and `docs/onboarding/api-status-and-roadmap.md` in the relevant repository.

## Workspace map

| Repository | Role today | Best starting docs |
| --- | --- | --- |
| `nordicintel-core` | Canonical domain language, shared models, JSON-stat model/codec, adapter protocols, PostgreSQL schema, migrations, repositories, and engine/session rules | `CONTEXT.md`, `README.md`, `docs/adapters.md`, `docs/database.md`, `docs/onboarding/core-domain-and-persistence.md` |
| `nordicintel-harvest` | Runtime that schedules, executes, and records harvest jobs | `README.md`, `docs/onboarding/harvest-runtime.md` |
| `nordicintel-adapter-pxweb2` | Concrete PxAPI v2 adapter package used by harvest workers | `README.md`, `docs/onboarding/adapter-contract.md` |
| `nordicintel-api` | API specification and planning repo; no runnable service is evident in the current checkout | `README.md`, `docs/onboarding/api-status-and-roadmap.md` |

## Recommended reading order

1. Read this file, then `CONTEXT.md` in `nordicintel-core`.
2. Read `README.md`, `docs/adapters.md`, and `docs/database.md` in `nordicintel-core`.
3. Read `README.md` and `docs/onboarding/harvest-runtime.md` in `nordicintel-harvest`.
4. Read `README.md` and `docs/onboarding/adapter-contract.md` in `nordicintel-adapter-pxweb2`.
5. Read `README.md` and `docs/onboarding/api-status-and-roadmap.md` in `nordicintel-api`.

That order starts with the shared language and persistence rules, then moves outward to runtime behavior, concrete provider integration, and finally the planned API surface.

## Ownership and boundary rules

### `nordicintel-core`

`nordicintel-core` is the contract and persistence spine of the workspace. It owns:

- the canonical glossary in `CONTEXT.md`
- shared application models
- the JSON-stat Dataset model and codec
- the adapter protocol described in `docs/adapters.md`
- the PostgreSQL schema, migration history, and repositories described in `docs/database.md`
- engine/session rules for short-lived API-style work versus pinned harvest ownership sessions

It does **not** own a web service or a background process.

### `nordicintel-harvest`

`nordicintel-harvest` owns the processes that use core:

- schedule admission
- job claiming
- heartbeat and cancellation
- stale-job recovery
- the traversal logic that decides whether a discovered table should be fetched now
- temporary operator commands until an API exists

It does **not** declare tables, ship migrations, or reimplement the shared HTTP client.

### `nordicintel-adapter-pxweb2`

`nordicintel-adapter-pxweb2` owns PxAPI v2 translation:

- upstream discovery
- native request construction
- provider auth wiring
- comparison-marker semantics
- mapping upstream catalog, metadata, and live data into core contracts

It does **not** access the database or mint canonical NordicIntel table IDs.

### `nordicintel-api`

`nordicintel-api` currently owns API-facing specifications and planning material. Based on the current checkout, it does **not** yet own a runnable service package.

### Cross-repo rules that matter most

- **Core owns the vocabulary.** Use the terms from `CONTEXT.md` consistently across all repos.
- **Core owns canonical identity.** Adapters return `provider_id` and `native_table_id`; core mints and resolves the canonical table ID.
- **Adapters never receive a database connection.** They translate upstream behavior only.
- **One harvest job always means one provider and one language.** Language is part of the request, not a filter applied later.
- **Migrations are a separate deployment task.** API and worker startup must not run them automatically.
- **Absence is not retirement.** A table missing from a later discovery run is left as-is in storage until a separate policy says otherwise.
- **Live data routing should use stored native identity.** Do not try to recover upstream identity by parsing a canonical slug.

## Domain vocabulary that must stay consistent

The glossary in `CONTEXT.md` in `nordicintel-core` is the canonical source. The terms below are the ones that most often cross repository boundaries.

| Term | Meaning |
| --- | --- |
| **Provider** | An upstream statistical publisher configured through one Adapter |
| **Table** | A stable, addressable catalogue resource that has metadata and can provide data |
| **Dataset** | The JSON-stat representation used for metadata or live observations |
| **Adapter** | A provider-family integration |
| **Discovery** | Enumeration of the Tables a Provider publishes in exactly one language |
| **Harvest Job** | One requested traversal of one Provider, or one Table, in one language |
| **Harvest Item** | The outcome of processing one upstream Table during a Harvest Job |
| **Language Metadata** | One language-specific catalog plus metadata Dataset for a Table |

The important practical consequence is that words such as “source”, “backend”, “run”, or “translation” are usually too vague to substitute safely for the terms above.

## End-to-end flow

### Metadata flow implemented today

1. A Provider is configured with an `adapter_type` and provider-specific settings.
2. `nordicintel-harvest` enqueues a job for one Provider and one language.
3. A worker claims that job on one physical database backend, resolves secrets, builds shared HTTP access, and instantiates the adapter named by the Provider.
4. The adapter performs Discovery in that language. Discovery states what is present; it does not infer meaning from what is absent.
5. For each discovered Table, harvest decides whether a refresh is needed. If so, the adapter fetches one `Language Metadata` result: catalog fields plus a metadata-only JSON-stat `Dataset`.
6. `nordicintel-core` validates and persists the accepted result:
   - `table_registry` keeps canonical identity, native identity, and operator/runtime controls
   - `table_metadata` keeps one language's catalog fields and metadata Dataset
   - `table_language_state` keeps comparison markers, freshness, and failure state
7. The stored metadata becomes the durable catalogue and search surface used by the NordicIntel workspace today.

### Live data and API access

A future API path is planned but not implemented in the current `nordicintel-api` checkout. The intended shape, based on `docs/onboarding/api-status-and-roadmap.md`, is:

1. read catalogue and metadata through core repositories
2. use stored native table identity to route live data requests back through an adapter
3. return live observations as JSON-stat without duplicating adapter or schema logic in the API layer

That is an intended direction, not a claim that the HTTP service exists today.

## Implemented today vs. still planned

| Topic | Status |
| --- | --- |
| Shared domain language, JSON-stat model, schema ownership, migrations, repositories, and DB session rules in `nordicintel-core` | Implemented today |
| Scheduler, worker, bootstrap CLI, cancellation, heartbeat, and stale-job recovery in `nordicintel-harvest` | Implemented today |
| PxAPI v2 discovery, metadata fetch, data fetch, and refresh-marker logic in `nordicintel-adapter-pxweb2` | Implemented today |
| Bootstrap as the temporary operator control plane | Implemented today, but explicitly temporary until an API exists |
| Public/admin API service code in `nordicintel-api` | Still planned; current repo evidence is specification and roadmap material rather than a runnable service |
| A single confirmed source of truth between `docs/pxapi2.yml` and `docs/pxapi2.json` in `nordicintel-api` | Not established by the current docs |
| Any policy that turns later discovery absence into retirement or deletion | Not implemented; current behavior is to keep accepted metadata as-is |

## What should feel stable to a new contributor

These points appear to be the durable architecture of the workspace today:

- `nordicintel-core` defines the shared language and persistence contract.
- `nordicintel-harvest` is the runtime that keeps the catalogue current.
- Adapter packages are separate deployable integrations that translate upstream systems into core contracts.
- The API layer should be thin over core repositories and adapter-routed live data rather than a second source of business rules.

If a change proposal crosses one of those boundaries, treat it as architecture work rather than as a local refactor.
