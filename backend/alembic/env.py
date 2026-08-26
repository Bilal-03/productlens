from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from alembic import context

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database_url = os.getenv("DATABASE_ADMIN_URL")
if database_url:
    # Supabase's Connect panel returns a standard ``postgresql://`` URI,
    # while this project uses psycopg 3. Normalize the driver here so users
    # can paste the provider URI directly without installing psycopg2.
    parsed_url = make_url(database_url)
    if parsed_url.drivername in {"postgres", "postgresql"}:
        parsed_url = parsed_url.set(drivername="postgresql+psycopg")
    normalized_url = parsed_url.render_as_string(hide_password=False)
    # Alembic's ConfigParser interpolation treats percent-encoded password
    # characters as interpolation markers; escape them before setting the
    # URL while leaving the actual connection URL unchanged.
    config.set_main_option("sqlalchemy.url", normalized_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
