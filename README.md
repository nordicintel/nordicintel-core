# nordicintel-core

Shared contracts and infrastructure for NordicIntel applications and provider
adapters. The package contains no web service or background process of its own.

Table metadata composes catalog attributes with the shared JSON-stat 2.0 Dataset
from `nordicintel-model`. Metadata Datasets have `value: []`; live data uses the same
Dataset type with observations. Tables have a stable canonical ID and a provider/native
identity pair. There is no alternate-identifier registry.

Requires Python 3.12+. For development, check out `nordicintel-model` next to this
repository; uv uses that local editable package. Release wheels declare a normal
`nordicintel-model>=0.1.0,<0.2` dependency. See [the metadata model](docs/table-metadata-proposal.md)
and [database integration](docs/database.md).

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

CI checks out the sibling model repository. If that repository is private, provide
`NORDICINTEL_READ_TOKEN` with read access to it; otherwise CI uses its ordinary GitHub token.
