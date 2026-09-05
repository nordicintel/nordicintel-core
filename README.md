# nordicintel-core

Shared contracts and infrastructure for NordicIntel applications and provider
adapters. The package contains no web service or background process of its own.

The Table/Dataset models and initial SQL definitions are being realigned.
Repository queries are deliberately deferred and currently incompatible with the
revised schema. See [database integration](docs/database.md) before using migrations
or repositories. This intermediate version is not deployment-ready.

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
