"""the episode's proposed set description (editable text the owner may send to the image API)

Revision ID: 0009
Revises: 0008
Additive: a nullable JSON column. Nothing is generated from it unless the owner clicks "Generate this set".
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("set_proposal", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("episodes", "set_proposal")
