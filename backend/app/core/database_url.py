"""
Database URL security, structural validation, and environment isolation for LedgerLine.

SAFETY & ISOLATION POLICIES:
- Test and migration databases must strictly target the approved local database: 'ledgerline_test'.
- Development database 'ledgerline' is strictly prohibited during test execution and migration commands.
- Drivers are restricted to approved PostgreSQL drivers (and SQLite ':memory:' exclusively for tests).
- Hosts are restricted to approved local loopback interfaces (localhost, 127.0.0.1, ::1).
- Ports are strictly restricted to the standard PostgreSQL port (5432).
- URL parsing is performed structurally via SQLAlchemy make_url (never fragile substring matching).
- All error and log messages sanitize connection strings so credentials and passwords are never disclosed.
"""

from typing import Final

from sqlalchemy.engine import URL, make_url

APPROVED_DATABASE_NAME: Final[str] = "ledgerline_test"
APPROVED_LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})
APPROVED_POSTGRES_DRIVERS: Final[frozenset[str]] = frozenset({"postgresql", "postgresql+psycopg2"})
APPROVED_POSTGRES_PORT: Final[int] = 5432


def validate_postgres_test_database_url(
    url: str | None,
    context_name: str = "Database",
) -> URL:
    """Validate that a PostgreSQL URL strictly targets the approved local test database.

    Args:
        url: Raw connection URL string.
        context_name: Context identifier for diagnostic messages (e.g. 'Test database', 'Migration').

    Returns:
        SQLAlchemy URL instance.

    Raises:
        ValueError: If the URL is missing, empty, or structurally unparseable.
        RuntimeError: If the URL targets an unapproved database, remote host, unexpected port,
                      or unsupported driver.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError(f"{context_name} URL is empty or not configured.")

    try:
        parsed = make_url(url.strip())
    except Exception:
        raise ValueError("Invalid or malformed database URL.") from None

    safe_url_str = parsed.render_as_string(hide_password=True)
    driver = (parsed.drivername or "").lower()

    # 1. Driver verification
    if driver not in APPROVED_POSTGRES_DRIVERS:
        raise RuntimeError(
            f"SAFETY VIOLATION: Driver '{driver}' in '{safe_url_str}' is not supported for {context_name.lower()}. "
            f"Only approved PostgreSQL drivers are permitted: {sorted(APPROVED_POSTGRES_DRIVERS)}."
        )

    # 2. Host verification
    host = (parsed.host or "").lower()
    if not host:
        raise RuntimeError(
            f"SAFETY VIOLATION: {context_name} URL '{safe_url_str}' does not specify a host. "
            f"Must target an approved local host: {sorted(APPROVED_LOCAL_HOSTS)}."
        )

    if host not in APPROVED_LOCAL_HOSTS:
        raise RuntimeError(
            f"SAFETY VIOLATION: Host '{host}' in '{safe_url_str}' is not an approved local host "
            f"(approved: {sorted(APPROVED_LOCAL_HOSTS)}). Remote database connections are strictly prohibited."
        )

    # 3. Port verification
    port = parsed.port
    if port != APPROVED_POSTGRES_PORT:
        raise RuntimeError(
            f"SAFETY VIOLATION: {context_name} URL '{safe_url_str}' must use port {APPROVED_POSTGRES_PORT} "
            f"(found: {port}). Unexpected ports are rejected."
        )

    # 4. Target database verification
    raw_db = parsed.database or ""
    db_name = raw_db.split("#")[0].split("?")[0].strip("/").lower()

    if not db_name:
        raise RuntimeError(
            f"SAFETY VIOLATION: {context_name} URL '{safe_url_str}' does not specify a target database."
        )

    if db_name == "ledgerline":
        raise RuntimeError(
            f"SAFETY VIOLATION: {context_name} attempted to connect to development database 'ledgerline' "
            f"at '{safe_url_str}'. Must exclusively target the approved test database ('{APPROVED_DATABASE_NAME}')."
        )

    if db_name != APPROVED_DATABASE_NAME:
        raise RuntimeError(
            f"SAFETY VIOLATION: Target database '{db_name}' in '{safe_url_str}' is not the approved "
            f"test database (approved: '{APPROVED_DATABASE_NAME}')."
        )

    return parsed


def validate_migration_database_url(url: str | None) -> str:
    """Validate that MIGRATION_DATABASE_URL is explicitly provided and safe.

    MIGRATION COMMAND REQUIREMENTS:
    - Must be explicitly supplied via MIGRATION_DATABASE_URL.
    - Must never silently fall back to DATABASE_URL or settings.database_url.
    - Must target PostgreSQL database 'ledgerline_test' on localhost:5432.
    - Rejects SQLite (even in-memory), remote hosts, and all unexpected databases.

    Args:
        url: Raw migration database connection URL.

    Returns:
        Validated connection URL string.

    Raises:
        ValueError: If MIGRATION_DATABASE_URL is missing or unparseable.
        RuntimeError: If the URL fails any security constraint.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError(
            "MIGRATION_DATABASE_URL is not set or empty. "
            "Alembic migration commands require an explicitly supplied MIGRATION_DATABASE_URL "
            f"targeting '{APPROVED_DATABASE_NAME}' on localhost:{APPROVED_POSTGRES_PORT}. "
            "Migration commands must never silently fall back to DATABASE_URL or the development database."
        )

    # Validate strictly as a PostgreSQL test database URL
    validate_postgres_test_database_url(url, context_name="Migration database")
    return url.strip()


def assert_test_database_url_safety(url: str | None) -> None:
    """Validate that a database URL strictly targets an approved test database.

    Permits:
    - SQLite in-memory (':memory:') exclusively for isolated unit tests.
    - PostgreSQL targeting 'ledgerline_test' on localhost:5432.

    Rejects:
    - Persistent / file-based SQLite.
    - Development database 'ledgerline'.
    - Remote hosts, unexpected ports, and all unapproved drivers or databases.

    Args:
        url: Database connection string to validate.

    Raises:
        ValueError: If the URL is missing, empty, or unparseable.
        RuntimeError: If the target database fails safety constraints.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError("TEST_DATABASE_URL is empty or not configured.")

    try:
        parsed = make_url(url.strip())
    except Exception:
        raise ValueError("Invalid or malformed database URL.") from None

    safe_url_str = parsed.render_as_string(hide_password=True)
    driver = (parsed.drivername or "").lower()

    # SQLite handling: ONLY in-memory (':memory:') is approved for isolated unit tests
    if driver.startswith("sqlite"):
        db_target = (parsed.database or "").strip("/").lower()
        if db_target == ":memory:":
            return
        raise RuntimeError(
            f"SAFETY VIOLATION: File-based SQLite test database '{safe_url_str}' is not permitted. "
            "Only SQLite in-memory (':memory:') is approved for isolated tests."
        )

    # For relational / PostgreSQL databases, apply full strict validation
    validate_postgres_test_database_url(url, context_name="Test database")
