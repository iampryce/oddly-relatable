"""the Bin: soft-deleted items (restorable for 30 days); cleared failed jobs

Revision ID: 0013
Revises: 0012
Additive: a new table and a nullable column (jobs.cleared_at: a failed job the owner cleared from Production).
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bin_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_by", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("files", sa.JSON(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.UniqueConstraint("kind", "ref", name="uq_bin_kind_ref"),
    )
    op.add_column("jobs", sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "cleared_at")
    op.drop_table("bin_items")
