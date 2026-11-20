"""dialogue display per episode: speech bubbles, none or captions

Revision ID: 0007
Revises: 0006
Additive only. Existing episodes keep speech bubbles (server default "bubbles", owner decision 2026-11-20); new
episodes take the default from Settings > Production (initially "none"). The previous release ignores the column.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("dialogue_display", sa.String(length=10), nullable=False, server_default="bubbles"))


def downgrade() -> None:
    op.drop_column("episodes", "dialogue_display")
