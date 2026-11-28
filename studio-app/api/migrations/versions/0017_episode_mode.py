"""the episode's production mode (cartoon | cinematic)

Revision ID: 0017
Revises: 0016
Additive: one nullable column, filled with 'cartoon' for every episode that already exists (they keep today's flow
exactly). New episodes choose 'cartoon' or 'cinematic' when they are created (cinematic.py); NULL is read as 'cartoon'.
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("mode", sa.String(length=12), nullable=True))
    op.execute("UPDATE episodes SET mode = 'cartoon' WHERE mode IS NULL")


def downgrade() -> None:
    op.drop_column("episodes", "mode")
