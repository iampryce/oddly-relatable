"""One-off migration: copy a studio database (SQLite file from the workstation) into this deployment's database.

    python -m oddstudio.migrate_import /data/migrate/studio.db [--replace]

Rows keep their ids, so assets, jobs, reviews and segments stay linked exactly as before. Media files are copied
separately into <work_dir>/storage (same relative keys). Refuses to run on a database that already has episodes unless
--replace is given (then every studio table is emptied first; Alembic's version table is kept). Character 01's seed row
and settings are replaced by the imported ones. Job logs keep their original text (history).
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, func, select, text

from .db import Base, engine
from . import models  # noqa: F401  (registers the tables)


def main(path: str, replace: bool) -> None:
    src = create_engine(f"sqlite:///{path}")
    dst = engine()
    tables = Base.metadata.sorted_tables
    with dst.begin() as d:
        n_eps = d.execute(select(func.count()).select_from(models.Episode.__table__)).scalar()
        if n_eps and not replace:
            sys.exit(f"the target already has {n_eps} episode(s); pass --replace to overwrite it")
        names = ", ".join(f'"{t.name}"' for t in tables)
        if dst.dialect.name == "postgresql":
            d.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        else:
            for t in reversed(tables):
                d.execute(t.delete())
        with src.connect() as s:
            have = set(src.dialect.get_table_names(s))
            for t in tables:
                if t.name not in have:
                    print(f"{t.name}: not in the source, skipped")
                    continue
                src_cols = {c["name"] for c in src.dialect.get_columns(s, t.name)}
                cols = [c for c in t.columns if c.name in src_cols]
                rows = [dict(r._mapping) for r in s.execute(select(*cols))]
                if rows:
                    d.execute(t.insert(), rows)
                print(f"{t.name}: {len(rows)} rows")
        if dst.dialect.name == "postgresql":
            for t in tables:
                if "id" in t.columns and t.columns["id"].autoincrement in (True, "auto") and t.columns["id"].primary_key:
                    d.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{t.name}\"', 'id'), "
                                   f"COALESCE((SELECT MAX(id) FROM \"{t.name}\"), 0) + 1, false)"))
    print("import complete")


if __name__ == "__main__":
    main(sys.argv[1], "--replace" in sys.argv[2:])
