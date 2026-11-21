"""per-scene sets: the extra sets an episode may change to, and each storyboard scene's own set

Revision ID: 0011
Revises: 0010
Additive: nullable columns; existing episodes and scenes have none, so every scene renders on the episode's set.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("scene_set_ids", sa.JSON(), nullable=True))
    op.add_column("storyboard_scenes", sa.Column("set_id", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("storyboard_scenes", "set_id")
    op.drop_column("episodes", "scene_set_ids")
