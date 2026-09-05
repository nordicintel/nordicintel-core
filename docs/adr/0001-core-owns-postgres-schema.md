# Core owns the shared PostgreSQL schema

NordicIntel Core owns one Alembic history backed by explicit SQL resources, while applications use
direct Psycopg repositories and never migrate on startup. This keeps independently deployed API and
harvest consumers on one versioned schema contract without introducing an ORM; SQLAlchemy is used
only by Alembic, and migrations run as a standalone deployment task.
