"""long-form episodes: format, outline versions, segments

Revision ID: 0003
Revises: 0002
Additive only: older code keeps working on this schema.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("ideas", "episodes"):
        op.add_column(table, sa.Column("format", sa.String(length=10), nullable=False, server_default="short"))
        op.add_column(table, sa.Column("continues_episode_id", sa.Integer(), nullable=True))
    op.add_column("episodes", sa.Column("outline_version", sa.Integer(), nullable=True))
    op.add_column("episodes", sa.Column("approved_outline_version", sa.Integer(), nullable=True))
    op.create_table(
        "outline_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("episode_id", sa.Integer(), sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("episode_id", "version"),
    )
    op.create_table(
        "segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("episode_id", sa.Integer(), sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("parts", sa.JSON(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reused_from", sa.Integer(), nullable=True),
        sa.Column("video_asset_id", sa.Integer(), nullable=True),
        sa.Column("audio_asset_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("render_seconds", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("segments")
    op.drop_table("outline_versions")
    op.drop_column("episodes", "approved_outline_version")
    op.drop_column("episodes", "outline_version")
    for table in ("episodes", "ideas"):
        op.drop_column(table, "continues_episode_id")
        op.drop_column(table, "format")
