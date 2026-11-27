"""the episode's drawing style (cast from video)

Revision ID: 0016
Revises: 0015
Additive: one nullable column. episodes.style: NULL = not chosen yet (older episodes keep working exactly as before and
are treated as the house stick-man style downstream); otherwise one of the cast style presets (cast_from_video.STYLES).
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("style", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("episodes", "style")
