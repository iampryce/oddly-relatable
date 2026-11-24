"""the episode's frame layout and each storyboard scene's shot list

Revision ID: 0015
Revises: 0014
Additive: two nullable columns. episodes.layout: NULL = "full" (the whole 9:16 frame, as before); "band" = a 16:9
picture band in the middle of the 9:16 frame, captions below. storyboard_scenes.shots: NULL = no shot list (the
renderers decide the shots as before). Reaction beats need no column: they live inside the lines JSON.
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("layout", sa.String(length=10), nullable=True))
    op.add_column("storyboard_scenes", sa.Column("shots", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("storyboard_scenes", "shots")
    op.drop_column("episodes", "layout")
