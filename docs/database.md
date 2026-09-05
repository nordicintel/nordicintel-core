# Database integration

## Model/schema rewrite in progress

The initial SQL definitions have been rewritten against the combined Table/Dataset
metadata contract. **Repository implementations and packaged query files are
intentionally unchanged pending review of this model.** They are not compatible
with the revised definitions yet; do not use this intermediate state for deployment.
Existing repository integration tests have not been rewritten or disabled to hide
that mismatch. `tests/test_schema.py` tests the definitions directly in an isolated
transactional schema, including complete metadata storage and downgrade/re-upgrade.

`dataset` owns canonical/native identity, serving mode, operator controls, worker
availability, and `retired` (absence after authoritative discovery).
`dataset_metadata` owns the language-scoped combined metadata, including the
publisher's nullable `discontinued` flag. Retirement, publisher discontinuation,
operator disabling and worker availability are distinct states.

Every normalized metadata field is represented: scalar fields and text arrays are
columns; typed links, paths, contacts, PX details and extension maps use JSONB;
dimensions and categories are language-scoped child relations with `index` columns.
Neither `id`/`size` envelope arrays nor observations are stored. Comparison state,
local harvest timestamps and the GIN-backed search projection remain language-scoped.
Model validation owns nested semantic checks; SQL enforces keys, foreign keys,
unique indexes, required scalar values, enum values and JSON container types.

This edits the initial baseline, not an additive upgrade migration. A database
already stamped `0001_initial` will not be transformed by `upgrade head`. Migration
history/release handling must be settled before deploying the revised schema;
no existing database has been reset or migrated as part of this rewrite.

## Repository usage (pending alignment)

Applications create and own a Psycopg connection, then pass it to repositories:

```python
from nordicintel_core.database import HarvestRepository, connect

with connect(database_url) as connection:
    jobs = HarvestRepository(connection).list_jobs(limit=50)
```

Connections use autocommit so repository transaction blocks define atomic boundaries. A worker must
retain the connection that claimed a job for the entire execution, then finalize the job and release
its provider advisory lock before closing it. It must never reconnect and resume protected writes.

Run migrations exactly once as a separate deployment task:

```text
NORDICINTEL_DATABASE_URL=postgresql://... \
python -m nordicintel_core.database migrate upgrade
```

Supported migration commands are `upgrade [revision]`, `downgrade [revision]`, `current`, and
`check`. Upgrade defaults to `head`; downgrade defaults to `base`. API and worker startup must not
invoke them automatically.

Deploy additive migrations before consumers that require them. Pin a tested core version in every
API, worker, and adapter lockfile; remove old schema fields only after all consumers stop using them.
