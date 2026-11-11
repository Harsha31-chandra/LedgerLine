"""
Database engine, session factory, and dependency injection for LedgerLine.

Guarantees:
- Database credentials loaded strictly from environment configuration.
- Engine configured with pool_pre_ping for connection health.
- Safe session factory defaults: autocommit=False, autoflush=False, expire_on_commit=False.
- get_db dependency guarantees session closure via try...finally block.
- Tables are NOT created automatically on startup (Alembic handles migrations).
"""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import settings
from backend.app.core.database_url import validate_runtime_database_url


def create_app_engine(
    database_url: str | None = None,
    *,
    app_env: str | None = None,
    allowed_hosts: set[str] | list[str] | None = None,
    allowed_databases: set[str] | list[str] | None = None,
    allowed_ports: set[int] | list[int] | None = None,
    **kwargs: Any,
) -> Engine:
    """Create a configured SQLAlchemy engine for application runtime operations.

    FAIL-CLOSED SECURITY POLICY:
    - Requires a dedicated runtime database connection (database_url argument or settings.app_database_url).
    - Environment-aware validation: enforces local loopback policy in development/test,
      and requires explicit host/database allowlists in production.
    - Validates that runtime connections strictly use role 'ledgerline_app' and an approved database.
    - Fails closed on missing, empty, malformed, unallowlisted, or privileged connection attempts.
    - Zero fallback to privileged migration, development admin, or superuser URLs.
    - Guarantees engine health with pool_pre_ping.
    """
    raw_url = database_url if database_url is not None else settings.app_database_url
    effective_env = app_env if app_env is not None else settings.app_env
    effective_hosts = allowed_hosts if allowed_hosts is not None else settings.db_allowed_hosts_list
    effective_dbs = allowed_databases if allowed_databases is not None else settings.db_allowed_databases_list
    effective_ports = allowed_ports if allowed_ports is not None else settings.db_allowed_ports_list

    validated_url = validate_runtime_database_url(
        raw_url,
        app_env=effective_env,
        allowed_hosts=effective_hosts,
        allowed_databases=effective_dbs,
        allowed_ports=effective_ports,
    )

    engine_kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
    }
    # Pool sizing only applies to QueuePool (standard for PostgreSQL)
    if "sqlite" not in validated_url:
        engine_kwargs.update(
            {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_recycle": 1800,
            }
        )
    engine_kwargs.update(kwargs)
    return create_engine(validated_url, **engine_kwargs)


# Primary application engine
engine: Engine = create_app_engine()

# Session factory producing isolated Session instances
SessionFactory: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a managed database session.

    Guarantees that any failed transaction is rolled back and that
    the session is cleanly closed when the request lifecycle ends.
    """
    session: Session = SessionFactory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
