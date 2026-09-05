# Core owns the shared PostgreSQL schema

> Superseded by [0002](0002-sqlalchemy-owns-schema-and-crud.md). Core still owns the
> schema and one Alembic history, but it is defined by a SQLAlchemy declarative model
> rather than hand-written SQL resources.

NordicIntel Core owns one Alembic history backed by explicit SQL resources, while applications use
direct Psycopg repositories and never migrate on startup. This keeps independently deployed API and
harvest consumers on one versioned schema contract without introducing an ORM; SQLAlchemy is used
only by Alembic, and migrations run as a standalone deployment task.
