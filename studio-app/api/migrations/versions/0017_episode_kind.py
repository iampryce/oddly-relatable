"""the episode type (narrated shorts)

Revision ID: 0017
Revises: 0016
Additive: one nullable column. episodes.kind: NULL = the classic episode (every existing episode keeps working exactly
as before); "narrated_short" = a narrated stick-man short made with the New short wizard (narrated_short.py). The
wizard's own state lives in the settings table (short:<episode id>), like the other guided steps.
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("kind", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("episodes", "kind")
