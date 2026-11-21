"""the episode's own set (background), chosen explicitly

Revision ID: 0008
Revises: 0007
Additive. Existing episodes get the set the acting renderer picks for them today, recorded once, so nothing they
render changes: the first storyboard scene's location when that is a set the renderer can stage (an approved studio
set or a repository plate with blocking), else Settings > Production's environment if it can be staged, else the
living room. New episodes start with no set: production refuses to start until the owner chooses one (owner decision
2026-11-21: no silent default). The previous release ignores the column.
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

REPO_SETS = Path(__file__).resolve().parents[4] / "production" / "animation" / "sets"
LIVING_ROOM = "living-room-empty-03"


def _json(v):
    if isinstance(v, (bytes, str)):
        try:
            return json.loads(v)
        except ValueError:
            return {}
    return v or {}


def upgrade() -> None:
    op.add_column("episodes", sa.Column("set_id", sa.String(length=80), nullable=True))
    bind = op.get_bind()
    rows = dict(bind.execute(sa.text("select key, value from settings where key in ('_sets', 'production')")).fetchall())
    studio = {k for k, r in _json(rows.get("_sets")).items() if isinstance(r, dict) and r.get("status") == "approved"}
    usable = studio | {p.stem for p in REPO_SETS.glob("*.json")}
    production = _json(rows.get("production")).get("environment") or LIVING_ROOM
    fallback = production if production in usable else LIVING_ROOM
    for (eid,) in bind.execute(sa.text("select id from episodes")).fetchall():
        first = bind.execute(sa.text("select location from storyboard_scenes where episode_id = :e order by position limit 1"),
                             {"e": eid}).scalar()
        chosen = first if first in usable else fallback
        bind.execute(sa.text("update episodes set set_id = :s where id = :e"), {"s": chosen, "e": eid})


def downgrade() -> None:
    op.drop_column("episodes", "set_id")
