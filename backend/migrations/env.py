"""
Alembic migration environment for LedgerLine.

DATABASE ISOLATION POLICY:
- Requires an explicitly supplied MIGRATION_DATABASE_URL environment variable.
- NEVER falls back to DATABASE_URL, settings.database_url, or the development database.
- Strictly validates that migrations target the dedicated 'ledgerline_test' database on localhost:5432.
- Validation occurs before any database engine is created or connection is opened.
- Configures SQLAlchemy metadata for auto-generation of migration scripts.
"""

from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import create_engine, pool

from backend.app.config import settings
from backend.app.core.database_url import validate_migration_database_url
from backend.app.models import Base

# Alembic Config object
config = context.config

# Logging configuration
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate — registered on Base.metadata
target_metadata = Base.metadata


def get_migration_url() -> str:
    """Retrieve and validate the explicitly required MIGRATION_DATABASE_URL.

    Must never fall back to DATABASE_URL, settings.database_url, or the development database.

    Returns:
        Validated connection URL string.

    Raises:
        ValueError: If MIGRATION_DATABASE_URL is missing, empty, or unparseable.
        RuntimeError: If MIGRATION_DATABASE_URL targets an unapproved database, remote host,
                      unexpected port, or unsupported driver.
    """
    raw_url = os.environ.get("MIGRATION_DATABASE_URL") or getattr(
        settings, "migration_database_url", None
    )
    validated_url = validate_migration_database_url(raw_url)

    # Set sanitized/escaped option in Alembic config to prevent ConfigParser '%' interpolation errors
    config.set_main_option("sqlalchemy.url", validated_url.replace("%", "%%"))
    return validated_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without a live DB connection."""
    migration_url = get_migration_url()
    context.configure(
        url=migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to the database and applies changes."""
    migration_url = get_migration_url()
    # Pass validated URL directly to create_engine, avoiding ConfigParser interpolation issues
    connectable = create_engine(
        migration_url,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
