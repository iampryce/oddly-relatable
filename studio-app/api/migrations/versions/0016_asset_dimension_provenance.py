"""the pose dimension, provenance and parent link on character assets (imported local generations)

Revision ID: 0016
Revises: 0015
Additive: six nullable columns on character_assets. posture, body_turn, view, framing: NULL = the default the studio has
always drawn (standing, front, front view, full figure), so every existing pose keeps today's behaviour. provenance:
NULL = made by the studio itself; an imported image keeps its manifest here. parent_asset_id: a plain id (no foreign
key, so the column drops cleanly on SQLite), e.g. a mask belongs to its pose. New asset kinds (mask, expression-sheet,
back-view) are plain strings in the existing kind column.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("character_assets", sa.Column("posture", sa.String(length=10), nullable=True))
    op.add_column("character_assets", sa.Column("body_turn", sa.String(length=10), nullable=True))
    op.add_column("character_assets", sa.Column("view", sa.String(length=10), nullable=True))
    op.add_column("character_assets", sa.Column("framing", sa.String(length=10), nullable=True))
    op.add_column("character_assets", sa.Column("provenance", sa.JSON(), nullable=True))
    op.add_column("character_assets", sa.Column("parent_asset_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    for col in ("parent_asset_id", "provenance", "framing", "view", "body_turn", "posture"):
        op.drop_column("character_assets", col)
