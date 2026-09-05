# nordicintel-core

Shared contracts and infrastructure for NordicIntel applications and provider
adapters. The package contains no web service or background process of its own.

## Start here

- `docs/workspace-architecture.md` — quickest map of the full four-repo workspace
- `CONTEXT.md` — canonical domain vocabulary used across the NordicIntel repos
- `docs/database.md` — schema ownership, repositories, and engine/session rules
- `docs/onboarding/core-domain-and-persistence.md` — source-backed onboarding note for this repository

Table metadata composes catalog attributes with the shared JSON-stat 2.0 Dataset
defined in `nordicintel_core.jsonstat`. Metadata Datasets have `value: []`; live data uses the same
Dataset type with observations. Tables have a stable canonical ID and a provider/native
identity pair. There is no alternate-identifier registry.

Requires Python 3.12+. Core contains its own Dataset model and codec.
See [the complete Dataset model](docs/jsonstat.md), [the metadata model](docs/table-metadata-proposal.md) and
[database integration](docs/database.md).

```bash
uv sync --all-extras --dev
uv run pytest
```

Models and adapter protocols are installed by default. Optional dependency groups
add the async HTTP client, PostgreSQL repositories, or migration tooling:

```bash
pip install "nordicintel-core[http]"
pip install "nordicintel-core[db]"
pip install "nordicintel-core[migrations]"
```

Apply the packaged database migrations as a standalone deployment task:

```bash
set NORDICINTEL_DATABASE_URL=postgresql://...
python -m nordicintel_core.database migrate upgrade
```

Importing `nordicintel_core` never reads the environment, opens a database
connection, or creates an HTTP client.
