"""character voice speed (Fish Audio prosody speed)

Revision ID: 0004
Revises: 0003
Additive only: a nullable column, so the previous release keeps working on this schema (rollback needs no restore).
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("characters", sa.Column("voice_speed", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("characters", "voice_speed")
