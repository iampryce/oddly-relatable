"""how each storyboard scene starts (seated / standing), from the script or the video notes

Revision ID: 0010
Revises: 0009
Additive: a nullable JSON column; existing scenes have none, so everyone stands as before.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("storyboard_scenes", sa.Column("staging", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("storyboard_scenes", "staging")
