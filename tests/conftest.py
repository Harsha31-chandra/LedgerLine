"""
Pytest configuration and programmatic database isolation safety for LedgerLine.

SAFETY ENFORCEMENT:
- Any test requiring a database MUST target an approved test database.
- Uses structural URL parsing via SQLAlchemy make_url (never fragile substring matching).
- Accepts only explicitly approved database names ('ledgerline_test' on localhost:5432).
- Accepts SQLite ':memory:' exclusively for isolated unit tests.
- Rejects 'ledgerline' (development database), remote hosts, unapproved drivers, and unexpected ports.
- Fails closed on missing, malformed, or empty URLs.
- Sanitizes error messages so credentials and passwords are never leaked.
- Skips live integration tests cleanly if PostgreSQL service is unreachable.
- Fails tests if connection fails due to authentication, invalid database, or misconfiguration.
- Disposes of engine instances safely on connection failure and fixture teardown.
"""

import socket
from typing import Final, Generator
from urllib.parse import quote, quote_plus

import pytest
from sqlalchemy import Engine, create_engine, make_url

from backend.app.config import settings
from backend.app.core.database_url import (
    APPROVED_DATABASE_NAME,
    APPROVED_LOCAL_HOSTS,
    APPROVED_POSTGRES_DRIVERS,
    APPROVED_POSTGRES_PORT,
    assert_test_database_url_safety,
)

# Explicit allowlist alias maintained for test suite backwards compatibility
APPROVED_TEST_DATABASES: Final[frozenset[str]] = frozenset({APPROVED_DATABASE_NAME})

__all__ = [
    "APPROVED_TEST_DATABASES",
    "APPROVED_DATABASE_NAME",
    "APPROVED_LOCAL_HOSTS",
    "APPROVED_POSTGRES_DRIVERS",
    "APPROVED_POSTGRES_PORT",
    "assert_test_database_url_safety",
    "enforce_test_database_isolation",
    "is_postgres_service_reachable",
    "sanitize_database_error_message",
    "test_engine",
]


def is_postgres_service_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check TCP reachability of PostgreSQL server socket.

    Returns:
        True if the socket connects successfully, False if connection is refused,
        timed out, or the host is unreachable.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def sanitize_database_error_message(exc: Exception, raw_password: str | None = None) -> str:
    """Sanitize database exception message, ensuring raw and URL-encoded passwords are never leaked."""
    msg = str(exc)
    if not raw_password:
        return msg

    # Collect all possible representations (plaintext, quote, quote_plus, and strict safe="" variants)
    variants = {
        raw_password,
        quote(raw_password),
        quote(raw_password, safe=""),
        quote_plus(raw_password),
        quote_plus(raw_password, safe=""),
    }
    for variant in sorted(variants, key=len, reverse=True):
        if variant:
            msg = msg.replace(variant, "******")
    return msg


@pytest.fixture(scope="session", autouse=True)
def enforce_test_database_isolation() -> None:
    """Autouse session fixture verifying test configuration before any test executes."""
    assert_test_database_url_safety(settings.test_database_url)


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    """Provide a verified test database engine.

    Skips tests with an explicit diagnostic message if the PostgreSQL service is unreachable.
    Fails tests if connection fails due to authentication, invalid database, permissions,
    or other database misconfigurations. Safely disposes of the engine on failure and teardown.
    """
    assert_test_database_url_safety(settings.test_database_url)
    parsed = make_url(settings.test_database_url)
    safe_url_str = parsed.render_as_string(hide_password=True)

    # SQLite handling (isolated unit tests)
    if (parsed.drivername or "").lower().startswith("sqlite"):
        engine = create_engine(settings.test_database_url)
        try:
            with engine.connect():
                pass
        except Exception as exc:
            engine.dispose()
            pytest.fail(f"SQLite test database connection to '{safe_url_str}' failed: {exc}")
        try:
            yield engine
        finally:
            engine.dispose()
        return

    host = parsed.host or "localhost"
    port = parsed.port or APPROVED_POSTGRES_PORT

    # 1. Distinguish genuine service availability: check if PostgreSQL service is accepting connections
    if not is_postgres_service_reachable(host, port):
        pytest.skip(
            f"PostgreSQL service unreachable at {host}:{port}. "
            "Skipping environment-dependent integration test."
        )

    # 2. Service is available; attempt connection via SQLAlchemy and PostgreSQL driver
    engine = create_engine(settings.test_database_url, pool_pre_ping=True)
    try:
        with engine.connect():
            pass
    except Exception as exc:
        engine.dispose()
        raw_pass = str(parsed.password) if parsed.password else None
        sanitized_reason = sanitize_database_error_message(exc, raw_pass)
        pytest.fail(
            f"PostgreSQL connection to '{safe_url_str}' failed due to database or "
            f"authentication misconfiguration: {sanitized_reason}"
        )

    try:
        yield engine
    finally:
        engine.dispose()
