"""Alembic environment: the URL comes from DATABASE_URL; the models are the source of the schema."""
from alembic import context

from oddstudio.config import get_settings
from oddstudio.db import Base
import oddstudio.models  # noqa: F401  (registers the tables)
from sqlalchemy import create_engine

target_metadata = Base.metadata
url = get_settings().database_url

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
