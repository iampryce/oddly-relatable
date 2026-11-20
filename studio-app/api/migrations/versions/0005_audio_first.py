"""audio-first episodes: source, audio rights, uploaded audio and its timed transcript

Revision ID: 0005
Revises: 0004
Additive only: new columns with defaults, so the previous release keeps working on this schema (rollback needs no restore).
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("source", sa.String(length=10), nullable=False, server_default="script"))
    op.add_column("episodes", sa.Column("audio_rights_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("episodes", sa.Column("audio_rights_source", sa.String(length=20), nullable=False, server_default=""))
    op.add_column("episodes", sa.Column("audio_asset_id", sa.Integer(), nullable=True))
    op.add_column("episodes", sa.Column("audio_transcript", sa.JSON(), nullable=True))


def downgrade() -> None:
    for col in ("audio_transcript", "audio_asset_id", "audio_rights_source", "audio_rights_confirmed", "source"):
        op.drop_column("episodes", col)
