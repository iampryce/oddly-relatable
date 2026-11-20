"""house style v2: per-character skin tone and the style version of each generated pose

Revision ID: 0006
Revises: 0004
Additive only: new columns with defaults, so the previous release keeps working on this schema (rollback needs no restore).

Merge order: the audio-first change adds revision 0005 (also on 0004). Whichever of the two merges second must set its
down_revision to the other's revision; test_migrations.test_single_head fails CI (and so blocks the auto-deploy) until
it does.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("characters", sa.Column("skin_tone", sa.String(length=40), nullable=False, server_default=""))
    op.add_column("character_assets", sa.Column("style_version", sa.String(length=4), nullable=False, server_default="v1"))


def downgrade() -> None:
    op.drop_column("character_assets", "style_version")
    op.drop_column("characters", "skin_tone")
