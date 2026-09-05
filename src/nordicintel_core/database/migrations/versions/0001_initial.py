"""Create NordicIntel metadata and harvest schema.

Revision ID: 0001_initial
Revises: None
"""

from alembic import op

from nordicintel_core.database.sql_files import read_migration

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(read_migration("0001_initial.up.sql"))


def downgrade() -> None:
    op.get_bind().exec_driver_sql(read_migration("0001_initial.down.sql"))
