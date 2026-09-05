# Database integration

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
