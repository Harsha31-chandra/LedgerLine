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


def create_app_engine(database_url: str | None = None, **kwargs: Any) -> Engine:
    """Create a configured SQLAlchemy engine.

    Args:
        database_url: Optional override URL (e.g. for testing). Defaults to settings.database_url.
        **kwargs: Additional engine keyword arguments.

    Returns:
        SQLAlchemy Engine instance.
    """
    url = database_url or settings.database_url
    engine_kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
    }
    # Pool sizing only applies to QueuePool (standard for PostgreSQL)
    if "sqlite" not in url:
        engine_kwargs.update(
            {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_recycle": 1800,
            }
        )
    engine_kwargs.update(kwargs)
    return create_engine(url, **engine_kwargs)


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
