"""the hook banner per episode: on or off, and its own text

Revision ID: 0014
Revises: 0013
Additive: two nullable columns. Existing episodes (owner decision 2026-11-22): the banner stays ON for script-first
episodes and for audio episodes already rendered (they keep their look); OFF for audio episodes not rendered yet.
New episodes: NULL = the default for their kind (on for script-first, off for audio).
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

RENDERED = ("producing", "production_failed", "video_review", "final_approved", "publishing", "published")


def upgrade() -> None:
    op.add_column("episodes", sa.Column("hook_banner", sa.Boolean(), nullable=True))
    op.add_column("episodes", sa.Column("hook_text", sa.String(length=120), nullable=True))
    eps = sa.table("episodes", sa.column("id", sa.Integer), sa.column("source", sa.String), sa.column("stage", sa.String),
                   sa.column("video_asset_id", sa.Integer), sa.column("hook_banner", sa.Boolean))
    conn = op.get_bind()
    for row in conn.execute(sa.select(eps.c.id, eps.c.source, eps.c.stage, eps.c.video_asset_id)):
        on = row.source != "audio" or row.video_asset_id is not None or row.stage in RENDERED
        conn.execute(eps.update().where(eps.c.id == row.id).values(hook_banner=on))


def downgrade() -> None:
    op.drop_column("episodes", "hook_text")
    op.drop_column("episodes", "hook_banner")
