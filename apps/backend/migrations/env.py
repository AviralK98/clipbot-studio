from alembic import context
from clipbot import models  # noqa: F401
from clipbot.config import get_settings
from clipbot.db import Base
from sqlalchemy import create_engine, pool

config = context.config
url = get_settings().database_url
if context.is_offline_mode():
    context.configure(
        url=url, target_metadata=Base.metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=url.startswith("sqlite")
        )
        with context.begin_transaction():
            context.run_migrations()
