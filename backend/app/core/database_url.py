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
- Runtime application connections must use the dedicated unprivileged role 'ledgerline_app' and never a privileged role.
- Migration connections must use a dedicated schema-owner role and never the runtime application role.
"""

from collections.abc import Sequence
from typing import Final

from sqlalchemy.engine import URL, make_url

APPROVED_DATABASE_NAME: Final[str] = "ledgerline_test"
APPROVED_LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})
APPROVED_POSTGRES_DRIVERS: Final[frozenset[str]] = frozenset({"postgresql", "postgresql+psycopg2"})
APPROVED_POSTGRES_PORT: Final[int] = 5432

# Role separation constants
APPROVED_RUNTIME_ROLE: Final[str] = "ledgerline_app"
PROHIBITED_RUNTIME_ROLES: Final[frozenset[str]] = frozenset(
    {"ledgerline", "ledgerline_migrator", "postgres", "root", "admin"}
)
APPROVED_RUNTIME_DATABASES: Final[frozenset[str]] = frozenset({"ledgerline", "ledgerline_test"})
APPROVED_MIGRATION_ROLES: Final[frozenset[str]] = frozenset({"ledgerline_migrator", "ledgerline"})


def is_test_database_name(name: str | None) -> bool:
    """Return True if the database name indicates an isolated test database."""
    if not name or not isinstance(name, str):
        return False
    clean = name.strip().lower()
    return (
        clean == APPROVED_DATABASE_NAME
        or clean.endswith("_test")
        or clean.startswith("test_")
        or "test" in clean
    )


def validate_postgres_test_database_url(
    url: str | None,
    context_name: str = "Database",
    allowed_ports: set[int] | Sequence[int] | None = None,
) -> URL:
    """Validate that a PostgreSQL URL strictly targets the approved local test database.

    Args:
        url: Raw connection URL string.
        context_name: Context identifier for diagnostic messages (e.g. 'Test database', 'Migration').
        allowed_ports: Optional allowed ports. Defaults to [5432].

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
    clean_allowed_ports = set(allowed_ports or [APPROVED_POSTGRES_PORT])
    if port not in clean_allowed_ports:
        ports_desc = APPROVED_POSTGRES_PORT if clean_allowed_ports == {APPROVED_POSTGRES_PORT} else sorted(clean_allowed_ports)
        raise RuntimeError(
            f"SAFETY VIOLATION: {context_name} URL '{safe_url_str}' must use port {ports_desc} "
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


def validate_runtime_database_url(
    url: str | None,
    *,
    app_env: str | None = None,
    allowed_hosts: set[str] | Sequence[str] | None = None,
    allowed_databases: set[str] | Sequence[str] | None = None,
    allowed_ports: set[int] | Sequence[int] | None = None,
) -> str:
    """Validate that the application runtime database URL is configured and fail-closed.

    ENVIRONMENT-AWARE FAIL-CLOSED SECURITY REQUIREMENTS:
    - Must be a non-empty, valid connection URL string.
    - Credentials and passwords are redacted from all exception messages.
    - Both in local and production environments, runtime connections MUST connect using
      the dedicated unprivileged role 'ledgerline_app'.
    - Privileged/superuser roles ('ledgerline', 'ledgerline_migrator', 'postgres', etc.)
      are strictly prohibited in all environments.
    - In local development/test environments (app_env in ('development', 'test', 'local')):
      - SQLite in-memory (':memory:') is permitted exclusively for unit tests. File-based SQLite is rejected.
      - PostgreSQL connections must target approved local loopback hosts (localhost, 127.0.0.1, ::1).
      - Must use approved standard port 5432.
      - Must target approved local databases ('ledgerline' or 'ledgerline_test').
    - In production environments (app_env in ('production', 'prod')):
      - SQLite is strictly prohibited (even in-memory).
      - Must have an explicit, non-empty database host allowlist (via DB_ALLOWED_HOSTS).
      - Must have an explicit, non-empty database name allowlist (via DB_ALLOWED_DATABASES).
      - Test databases ('ledgerline_test', *_test) are strictly rejected.
      - Unrestricted host or database access is strictly prevented (fail-closed).

    Args:
        url: Raw connection URL string.
        app_env: Explicit environment override ('development', 'test', 'production'). Defaults to settings.app_env.
        allowed_hosts: Explicit host allowlist override. Defaults to settings.db_allowed_hosts_list.
        allowed_databases: Explicit database allowlist override. Defaults to settings.db_allowed_databases_list.
        allowed_ports: Explicit port allowlist override. Defaults to settings.db_allowed_ports_list.

    Returns:
        Validated connection URL string.

    Raises:
        ValueError: If URL is missing, empty, or unparseable.
        RuntimeError: If URL fails any security or role-isolation constraint.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError("Application runtime database URL is empty or not configured.")

    try:
        parsed = make_url(url.strip())
    except Exception:
        raise ValueError("Invalid or malformed database URL.") from None

    safe_url_str = parsed.render_as_string(hide_password=True)
    driver = (parsed.drivername or "").lower()

    # Resolve effective environment and allowlists
    if app_env is None:
        try:
            from backend.app.config import settings

            effective_env = (settings.app_env or "development").strip().lower()
            if allowed_hosts is None and effective_env in ("production", "prod"):
                allowed_hosts = settings.db_allowed_hosts_list
            if allowed_databases is None and effective_env in ("production", "prod"):
                allowed_databases = settings.db_allowed_databases_list
            if allowed_ports is None:
                allowed_ports = settings.db_allowed_ports_list
        except Exception:
            effective_env = "development"
    else:
        effective_env = app_env.strip().lower()

    is_production = effective_env in ("production", "prod")

    # 1. Driver verification
    if driver.startswith("sqlite"):
        if is_production:
            raise RuntimeError(
                f"SAFETY VIOLATION: SQLite database '{safe_url_str}' is strictly prohibited in production environments. "
                "Production runtime must use an approved PostgreSQL deployment."
            )
        db_target = (parsed.database or "").strip("/").lower()
        if db_target == ":memory:":
            return url.strip()
        raise RuntimeError(
            f"SAFETY VIOLATION: File-based SQLite database '{safe_url_str}' is not permitted for runtime connections. "
            "Only SQLite in-memory (':memory:') is permitted for test overrides."
        )

    if driver not in APPROVED_POSTGRES_DRIVERS:
        raise RuntimeError(
            f"SAFETY VIOLATION: Driver '{driver}' in '{safe_url_str}' is not supported for runtime database. "
            f"Only approved PostgreSQL drivers are permitted: {sorted(APPROVED_POSTGRES_DRIVERS)}."
        )

    # 2. Host verification
    host = (parsed.host or "").lower()
    if not host:
        raise RuntimeError(
            f"SAFETY VIOLATION: Runtime database URL '{safe_url_str}' does not specify a host."
        )

    if is_production:
        clean_allowed_hosts = {h.strip().lower() for h in (allowed_hosts or []) if h and h.strip()}
        if not clean_allowed_hosts:
            raise RuntimeError(
                "SAFETY VIOLATION: Production database host allowlist is empty or not configured. "
                "Production requires explicit host allowlisting via DB_ALLOWED_HOSTS."
            )
        if host not in clean_allowed_hosts:
            raise RuntimeError(
                f"SAFETY VIOLATION: Database host '{host}' in '{safe_url_str}' is not in the explicit "
                f"production host allowlist (allowed: {sorted(clean_allowed_hosts)})."
            )
    else:
        if host not in APPROVED_LOCAL_HOSTS:
            raise RuntimeError(
                f"SAFETY VIOLATION: Host '{host}' in '{safe_url_str}' is not an approved local host "
                f"(approved: {sorted(APPROVED_LOCAL_HOSTS)}). Remote database connections are strictly prohibited in local/test environments."
            )

    # 3. Port verification
    port = parsed.port
    clean_allowed_ports = set(allowed_ports or [APPROVED_POSTGRES_PORT])
    if is_production:
        if port not in clean_allowed_ports:
            raise RuntimeError(
                f"SAFETY VIOLATION: Database port {port} in '{safe_url_str}' is not in the explicit "
                f"production port allowlist (allowed: {sorted(clean_allowed_ports)})."
            )
    else:
        if port not in clean_allowed_ports:
            ports_desc = APPROVED_POSTGRES_PORT if clean_allowed_ports == {APPROVED_POSTGRES_PORT} else sorted(clean_allowed_ports)
            raise RuntimeError(
                f"SAFETY VIOLATION: Runtime database URL '{safe_url_str}' must use port {ports_desc} "
                f"(found: {port}). Unexpected ports are rejected."
            )

    # 4. Target database verification
    raw_db = parsed.database or ""
    db_name = raw_db.split("#")[0].split("?")[0].strip("/").lower()
    if not db_name:
        raise RuntimeError(
            f"SAFETY VIOLATION: Runtime database URL '{safe_url_str}' does not specify a target database."
        )

    if is_production:
        if is_test_database_name(db_name):
            raise RuntimeError(
                f"SAFETY VIOLATION: Production runtime connection attempted to connect to test database '{db_name}' "
                f"at '{safe_url_str}'. Test databases are strictly prohibited in production environments."
            )
        clean_allowed_dbs = {d.strip().lower() for d in (allowed_databases or []) if d and d.strip()}
        if not clean_allowed_dbs:
            raise RuntimeError(
                "SAFETY VIOLATION: Production database allowlist is empty or not configured. "
                "Production requires explicit database allowlisting via DB_ALLOWED_DATABASES."
            )
        if db_name not in clean_allowed_dbs:
            raise RuntimeError(
                f"SAFETY VIOLATION: Target database '{db_name}' in '{safe_url_str}' is not in the explicit "
                f"production database allowlist (allowed: {sorted(clean_allowed_dbs)})."
            )
    else:
        if db_name not in APPROVED_RUNTIME_DATABASES:
            raise RuntimeError(
                f"SAFETY VIOLATION: Target database '{db_name}' in '{safe_url_str}' is not an authorized runtime "
                f"database (approved: {sorted(APPROVED_RUNTIME_DATABASES)})."
            )

    # 5. Role & Least-Privilege Verification (applies in ALL environments)
    user = (parsed.username or "").lower()
    if not user:
        raise RuntimeError(
            f"SAFETY VIOLATION: Runtime database URL '{safe_url_str}' does not specify a database user role."
        )

    if user in PROHIBITED_RUNTIME_ROLES:
        raise RuntimeError(
            f"SAFETY VIOLATION: Application runtime connection attempted to use privileged or unauthorized "
            f"role '{user}' at '{safe_url_str}'. The application runtime must connect using the dedicated "
            f"unprivileged role ('{APPROVED_RUNTIME_ROLE}'). Privileged, superuser, and migration roles are "
            "strictly prohibited for runtime application execution."
        )

    if user != APPROVED_RUNTIME_ROLE:
        raise RuntimeError(
            f"SAFETY VIOLATION: Application runtime connection must use dedicated role '{APPROVED_RUNTIME_ROLE}' "
            f"(found: '{user}' in '{safe_url_str}')."
        )

    return url.strip()


def validate_migration_database_url(
    url: str | None,
    *,
    app_env: str | None = None,
    allowed_hosts: set[str] | Sequence[str] | None = None,
    allowed_databases: set[str] | Sequence[str] | None = None,
    allowed_ports: set[int] | Sequence[int] | None = None,
) -> str:
    """Validate that MIGRATION_DATABASE_URL is explicitly provided and safe.

    MIGRATION COMMAND REQUIREMENTS:
    - Must be explicitly supplied via MIGRATION_DATABASE_URL.
    - Must never silently fall back to DATABASE_URL or settings.database_url.
    - In local/test environments, targets PostgreSQL database 'ledgerline_test' on localhost:5432.
    - In production environments, requires explicit host and database allowlists and rejects test databases.
    - Rejects SQLite (even in-memory).
    - Must never use the unprivileged application runtime role 'ledgerline_app'.

    Args:
        url: Raw migration database connection URL.
        app_env: Environment identifier ('development', 'test', 'production').
        allowed_hosts: Explicit host allowlist in production.
        allowed_databases: Explicit database allowlist in production.
        allowed_ports: Explicit port allowlist in production.

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

    # Determine environment
    if app_env is None:
        try:
            from backend.app.config import settings

            effective_env = (settings.app_env or "development").strip().lower()
            if allowed_hosts is None and effective_env in ("production", "prod"):
                allowed_hosts = settings.db_allowed_hosts_list
            if allowed_databases is None and effective_env in ("production", "prod"):
                allowed_databases = settings.db_allowed_databases_list
            if allowed_ports is None:
                allowed_ports = settings.db_allowed_ports_list
        except Exception:
            effective_env = "development"
    else:
        effective_env = app_env.strip().lower()

    is_production = effective_env in ("production", "prod")

    if is_production:
        try:
            parsed = make_url(url.strip())
        except Exception:
            raise ValueError("Invalid or malformed database URL.") from None

        safe_url_str = parsed.render_as_string(hide_password=True)
        driver = (parsed.drivername or "").lower()

        if driver.startswith("sqlite"):
            raise RuntimeError(
                f"SAFETY VIOLATION: Driver '{driver}' in '{safe_url_str}' is not supported for migration database. "
                f"Only approved PostgreSQL drivers are permitted: {sorted(APPROVED_POSTGRES_DRIVERS)}."
            )

        if driver not in APPROVED_POSTGRES_DRIVERS:
            raise RuntimeError(
                f"SAFETY VIOLATION: Driver '{driver}' in '{safe_url_str}' is not supported for migration database. "
                f"Only approved PostgreSQL drivers are permitted: {sorted(APPROVED_POSTGRES_DRIVERS)}."
            )

        host = (parsed.host or "").lower()
        clean_allowed_hosts = {h.strip().lower() for h in (allowed_hosts or []) if h and h.strip()}
        if not clean_allowed_hosts:
            raise RuntimeError(
                "SAFETY VIOLATION: Production database host allowlist is empty or not configured. "
                "Production migrations require explicit host allowlisting via DB_ALLOWED_HOSTS."
            )
        if host not in clean_allowed_hosts:
            raise RuntimeError(
                f"SAFETY VIOLATION: Migration database host '{host}' in '{safe_url_str}' is not in the explicit "
                f"production host allowlist (allowed: {sorted(clean_allowed_hosts)})."
            )

        port = parsed.port or APPROVED_POSTGRES_PORT
        clean_allowed_ports = set(allowed_ports or [APPROVED_POSTGRES_PORT])
        if port not in clean_allowed_ports:
            raise RuntimeError(
                f"SAFETY VIOLATION: Migration database port {port} in '{safe_url_str}' is not in the explicit "
                f"production port allowlist (allowed: {sorted(clean_allowed_ports)})."
            )

        raw_db = parsed.database or ""
        db_name = raw_db.split("#")[0].split("?")[0].strip("/").lower()
        if not db_name:
            raise RuntimeError(
                f"SAFETY VIOLATION: Migration database URL '{safe_url_str}' does not specify a target database."
            )
        if is_test_database_name(db_name):
            raise RuntimeError(
                f"SAFETY VIOLATION: Production migration connection attempted to target test database '{db_name}'. "
                "Test databases are strictly prohibited in production."
            )
        clean_allowed_dbs = {d.strip().lower() for d in (allowed_databases or []) if d and d.strip()}
        if not clean_allowed_dbs:
            raise RuntimeError(
                "SAFETY VIOLATION: Production database allowlist is empty or not configured. "
                "Production migrations require explicit database allowlisting via DB_ALLOWED_DATABASES."
            )
        if db_name not in clean_allowed_dbs:
            raise RuntimeError(
                f"SAFETY VIOLATION: Target database '{db_name}' in '{safe_url_str}' is not in the explicit "
                f"production database allowlist (allowed: {sorted(clean_allowed_dbs)})."
            )
    else:
        # In local/test environments, validate strictly as local test database
        clean_allowed_ports = set(allowed_ports or [APPROVED_POSTGRES_PORT])
        parsed = validate_postgres_test_database_url(
            url,
            context_name="Migration database",
            allowed_ports=clean_allowed_ports,
        )

    # Reject unprivileged runtime role for migrations in all environments
    user = (parsed.username or "").lower()
    if user == APPROVED_RUNTIME_ROLE:
        raise RuntimeError(
            f"SAFETY VIOLATION: Migration connection cannot use runtime application role '{APPROVED_RUNTIME_ROLE}'. "
            f"Routine schema migrations must use a dedicated migration/schema-owner role: {sorted(APPROVED_MIGRATION_ROLES)}."
        )

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
