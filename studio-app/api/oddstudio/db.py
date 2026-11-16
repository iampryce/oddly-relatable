"""Database engine and sessions (PostgreSQL in deployment; SQLite only for local tests)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_Session: sessionmaker | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url
        kw = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw = {"connect_args": {"check_same_thread": False}}
        _engine = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _fk(conn, _):  # enforce foreign keys in SQLite as PostgreSQL does
                conn.execute("PRAGMA foreign_keys=ON")
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine, _Session = None, None


def new_session() -> Session:
    engine()
    assert _Session is not None
    return _Session()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = new_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed by the route handlers themselves."""
    s = new_session()
    try:
        yield s
    finally:
        s.close()
