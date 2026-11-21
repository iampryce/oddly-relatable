"""timed actions per storyboard scene, from the video's beats

Revision ID: 0012
Revises: 0011
Additive: a nullable JSON column; scenes without actions render exactly as before.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("storyboard_scenes", sa.Column("actions", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("storyboard_scenes", "actions")
