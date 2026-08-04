import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

from web.config_dir.config import env
from web.db.models import Base

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Офлайн режим (генерация SQL-скриптов без подключения к БД)"""

    url = f"postgresql+asyncpg://{env.pg_admin}:{env.pg_admin_password}@{env.pg_host}:{env.pg_port}/{env.pg_db}"
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    """Онлайн режим с поддержкой asyncpg"""
    connectable = create_async_engine(
        url=f"postgresql+asyncpg://{env.pg_admin}:{env.pg_admin_password}@{env.pg_host}:{env.pg_port}/{env.pg_db}",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()