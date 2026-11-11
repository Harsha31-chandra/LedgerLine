"""
Unit tests verifying database configuration, engine creation, session management,
and hardened test database URL isolation safety.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.app.config import settings
from backend.app.core.database import create_app_engine, get_db
from backend.app.core.database_url import (
    APPROVED_DATABASE_NAME,
    APPROVED_LOCAL_HOSTS,
    APPROVED_POSTGRES_DRIVERS,
    APPROVED_POSTGRES_PORT,
    APPROVED_RUNTIME_ROLE,
    PROHIBITED_RUNTIME_ROLES,
    assert_test_database_url_safety,
    validate_migration_database_url,
    validate_runtime_database_url,
)


def test_database_url_loaded_from_settings():
    """Verify engine creation uses configuration settings without hardcoding."""
    assert settings.database_url is not None
    assert "postgresql://" in settings.database_url
    assert "ledgerline" in settings.database_url


def test_get_db_session_lifecycle():
    """Verify that get_db dependency yields a session and guarantees closure in finally block."""
    mock_session = MagicMock()
    with patch("backend.app.core.database.SessionFactory", return_value=mock_session):
        gen = get_db()
        session = next(gen)
        assert session == mock_session
        assert not mock_session.close.called

        # When generator finishes, session.close() must be called
        with pytest.raises(StopIteration):
            next(gen)
        assert mock_session.close.called
        assert not mock_session.rollback.called


def test_get_db_rolls_back_on_exception():
    """Verify that get_db rolls back the transaction before closing if an error occurs."""
    mock_session = MagicMock()
    with patch("backend.app.core.database.SessionFactory", return_value=mock_session):
        gen = get_db()
        session = next(gen)
        assert session == mock_session

        # Simulate exception raised within the request context
        with pytest.raises(RuntimeError, match="Simulated route error"):
            gen.throw(RuntimeError("Simulated route error"))

        assert mock_session.rollback.called
        assert mock_session.close.called


def test_create_app_engine_with_custom_url():
    """Verify that create_app_engine respects an explicit override URL (for test engines)."""
    custom_url = "sqlite:///:memory:"
    test_engine = create_app_engine(custom_url)
    assert str(test_engine.url) == custom_url
    test_engine.dispose()


# ---------------------------------------------------------------------------
# HARDENED TEST DATABASE URL SAFETY TESTS
# ---------------------------------------------------------------------------


def test_url_safety_accepts_valid_ledgerline_test():
    """Verify safety assertion accepts valid local test database URLs across loopback hosts."""
    # RFC 3986 requires IPv6 addresses in connection URIs to be enclosed in brackets: [::1]
    for host_spec in ["localhost", "127.0.0.1", "[::1]"]:
        # Standard postgresql driver
        url1 = f"postgresql://ledgerline:ledgerline_dev@{host_spec}:5432/ledgerline_test"
        assert_test_database_url_safety(url1)
        assert validate_migration_database_url(url1) == url1

        # postgresql+psycopg2 driver
        url2 = f"postgresql+psycopg2://ledgerline:ledgerline_dev@{host_spec}:5432/ledgerline_test"
        assert_test_database_url_safety(url2)
        assert validate_migration_database_url(url2) == url2


def test_url_safety_accepts_sqlite_in_memory_for_tests_only():
    """Verify SQLite in-memory is accepted for tests, but strictly rejected for migrations."""
    sqlite_memory = "sqlite:///:memory:"
    # Must succeed for test database isolation
    assert_test_database_url_safety(sqlite_memory)

    # Must fail for Alembic migrations (migrations require real PostgreSQL)
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*Driver 'sqlite'.*not supported"):
        validate_migration_database_url(sqlite_memory)


def test_url_safety_rejects_dev_database():
    """Verify safety assertion rejects the development database 'ledgerline'."""
    unsafe_url = "postgresql://ledgerline:secret@localhost:5432/ledgerline"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*development database 'ledgerline'"):
        assert_test_database_url_safety(unsafe_url)

    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*development database 'ledgerline'"):
        validate_migration_database_url(unsafe_url)


def test_url_safety_rejects_remote_hosts():
    """Verify safety assertion rejects remote hosts even when database name is 'ledgerline_test'."""
    remote_hosts = [
        "db.internal",
        "remote-host.company.com",
        "192.168.1.100",
        "10.0.0.5",
        "db-test-cluster.internal",
    ]
    for host in remote_hosts:
        remote_url = f"postgresql://user:secret@{host}:5432/ledgerline_test"
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*not an approved local host"):
            assert_test_database_url_safety(remote_url)
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*not an approved local host"):
            validate_migration_database_url(remote_url)


def test_url_safety_rejects_unexpected_port():
    """Verify safety assertion rejects non-standard or missing PostgreSQL ports."""
    # Custom port
    bad_port_url = "postgresql://ledgerline:secret@localhost:5433/ledgerline_test"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*must use port 5432"):
        assert_test_database_url_safety(bad_port_url)
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*must use port 5432"):
        validate_migration_database_url(bad_port_url)

    # Missing explicit port
    no_port_url = "postgresql://ledgerline:secret@localhost/ledgerline_test"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*must use port 5432"):
        assert_test_database_url_safety(no_port_url)
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*must use port 5432"):
        validate_migration_database_url(no_port_url)


def test_url_safety_rejects_unsupported_drivers():
    """Verify safety assertion rejects non-approved database drivers."""
    unsupported_drivers = [
        "mysql://user:pass@localhost:5432/ledgerline_test",
        "postgresql+asyncpg://user:pass@localhost:5432/ledgerline_test",
        "oracle://user:pass@localhost:5432/ledgerline_test",
    ]
    for url in unsupported_drivers:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*Driver .* not supported"):
            assert_test_database_url_safety(url)
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*Driver .* not supported"):
            validate_migration_database_url(url)


def test_url_safety_rejects_trailing_slash_bypass():
    """Verify safety assertion rejects development database even with a trailing slash."""
    bypass_url = "postgresql://ledgerline:secret@localhost:5432/ledgerline/"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*development database 'ledgerline'"):
        assert_test_database_url_safety(bypass_url)


def test_url_safety_rejects_username_containing_test():
    """Verify safety assertion rejects dev DB even when the username contains 'test'."""
    bypass_url = "postgresql://test_user:secret@localhost:5432/ledgerline"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*development database 'ledgerline'"):
        assert_test_database_url_safety(bypass_url)


def test_url_safety_query_string_and_fragment_variations():
    """Verify query strings and fragments are handled accurately by structural parser."""
    # Safe test DB with query parameter must pass
    safe_with_query = "postgresql://user:secret@localhost:5432/ledgerline_test?sslmode=disable"
    assert_test_database_url_safety(safe_with_query)
    assert validate_migration_database_url(safe_with_query) == safe_with_query

    # Dev DB with query parameter must be rejected
    dev_with_query = "postgresql://user:secret@localhost:5432/ledgerline?sslmode=disable"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*development database 'ledgerline'"):
        assert_test_database_url_safety(dev_with_query)

    # Dev DB with fragment must be rejected
    dev_with_frag = "postgresql://user:secret@localhost:5432/ledgerline#client_encoding=utf8"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*development database 'ledgerline'"):
        assert_test_database_url_safety(dev_with_frag)


def test_url_safety_rejects_unexpected_databases():
    """Verify safety assertion rejects unapproved database names (fail closed)."""
    unapproved = [
        "postgresql://user:pass@localhost:5432/ledgerline_prod",
        "postgresql://user:pass@localhost:5432/postgres",
        "postgresql://user:pass@localhost:5432/test",
        "postgresql://user:pass@localhost:5432/my_custom_db",
    ]
    for url in unapproved:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*not the approved test database"):
            assert_test_database_url_safety(url)
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*not the approved test database"):
            validate_migration_database_url(url)


def test_url_safety_rejects_file_based_sqlite():
    """Verify safety assertion rejects persistent file-based SQLite databases."""
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*File-based SQLite"):
        assert_test_database_url_safety("sqlite:///test.db")


def test_url_safety_rejects_missing_and_empty_urls():
    """Verify safety assertion rejects empty and whitespace-only URLs."""
    for empty in ["", "   ", None]:
        with pytest.raises(ValueError, match="URL is empty or not configured"):
            assert_test_database_url_safety(empty)
        with pytest.raises(ValueError, match="MIGRATION_DATABASE_URL is not set or empty"):
            validate_migration_database_url(empty)


def test_url_safety_rejects_malformed_urls():
    """Verify safety assertion rejects malformed URL strings."""
    with pytest.raises(ValueError, match="Invalid or malformed database URL"):
        assert_test_database_url_safety("not a valid url :/// ???")
    with pytest.raises(ValueError, match="Invalid or malformed database URL"):
        validate_migration_database_url("not a valid url :/// ???")


def test_migration_database_url_never_falls_back_to_dev_db(monkeypatch):
    """Verify migration URL resolution fails closed and never falls back to DATABASE_URL."""
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    # Confirm ValueError is raised when MIGRATION_DATABASE_URL is absent
    with pytest.raises(ValueError, match="MIGRATION_DATABASE_URL is not set or empty"):
        validate_migration_database_url(None)


def test_url_safety_does_not_expose_passwords_in_errors():
    """Verify that error messages sanitize connection strings and never leak passwords."""
    sensitive_url = "postgresql://user:super_secret_password@localhost:5432/ledgerline"
    with pytest.raises(RuntimeError) as exc_info:
        assert_test_database_url_safety(sensitive_url)

    error_msg = str(exc_info.value)
    assert "super_secret_password" not in error_msg
    assert "***" in error_msg

    with pytest.raises(RuntimeError) as exc_info_mig:
        validate_migration_database_url(sensitive_url)

    error_msg_mig = str(exc_info_mig.value)
    assert "super_secret_password" not in error_msg_mig
    assert "***" in error_msg_mig


def test_url_safety_malformed_urls_with_passwords_do_not_leak_via_cause():
    """Verify malformed URLs with passwords fail closed without leaking via __cause__ or traceback."""
    test_vectors = [
        "://user:SuperSecretPassword123!@localhost/db",
        "postgresql://user:P@ssw0rd!#123@::1:notaport/db",
    ]
    for malformed in test_vectors:
        # 1. Test assert_test_database_url_safety
        with pytest.raises(ValueError) as exc_info:
            assert_test_database_url_safety(malformed)
        err = exc_info.value
        assert str(err) == "Invalid or malformed database URL."
        assert "SuperSecretPassword123!" not in str(err)
        assert "P@ssw0rd!#123" not in str(err)
        assert "SuperSecretPassword123!" not in repr(err)
        assert "P@ssw0rd!#123" not in repr(err)
        assert err.__cause__ is None
        assert err.__suppress_context__ is True

        # 2. Test validate_migration_database_url
        with pytest.raises(ValueError) as exc_info_mig:
            validate_migration_database_url(malformed)
        err_mig = exc_info_mig.value
        assert str(err_mig) == "Invalid or malformed database URL."
        assert "SuperSecretPassword123!" not in str(err_mig)
        assert "P@ssw0rd!#123" not in str(err_mig)
        assert err_mig.__cause__ is None
        assert err_mig.__suppress_context__ is True


# ---------------------------------------------------------------------------
# POSTGRESQL TEST FIXTURE & SERVICE REACHABILITY TESTS
# ---------------------------------------------------------------------------


def test_is_postgres_service_reachable_helper():
    """Verify is_postgres_service_reachable returns True for live port and False for unused port."""
    from tests.conftest import is_postgres_service_reachable

    # Port 5432 is running and healthy via Docker
    assert is_postgres_service_reachable("localhost", 5432) is True
    assert is_postgres_service_reachable("127.0.0.1", 5432) is True

    # Port 5431 is unused and must return False
    assert is_postgres_service_reachable("localhost", 5431) is False


def test_sanitize_database_error_message():
    """Verify sanitize_database_error_message redacts sensitive password strings."""
    from tests.conftest import sanitize_database_error_message

    exc = Exception("Connection error with password SuperSecretToken456 failed")
    sanitized = sanitize_database_error_message(exc, "SuperSecretToken456")
    assert "SuperSecretToken456" not in sanitized
    assert "******" in sanitized

    # No password supplied leaves message unchanged
    clean_exc = Exception("Connection refused on port 5432")
    assert sanitize_database_error_message(clean_exc, None) == "Connection refused on port 5432"


def test_sanitize_database_error_message_redacts_plaintext_passwords():
    """Verify sanitize_database_error_message redacts plaintext passwords."""
    from tests.conftest import sanitize_database_error_message

    raw_pw = "super_secret_plain_pass_123"
    exc = Exception(f"Failed to authenticate with password {raw_pw} at host localhost")
    sanitized = sanitize_database_error_message(exc, raw_pw)
    assert raw_pw not in sanitized
    assert "******" in sanitized
    assert "Failed to authenticate with password ****** at host localhost" == sanitized


def test_sanitize_database_error_message_redacts_percent_encoded_passwords():
    """Verify sanitize_database_error_message redacts percent-encoded passwords with special characters."""
    from urllib.parse import quote
    from tests.conftest import sanitize_database_error_message

    # Test passwords containing special characters @, %, /, :, and +
    passwords_with_specials = [
        "p@ssword%456",
        "admin:secret/path+token@xyz",
        "p@ss%/ :+123",
    ]
    for raw_pw in passwords_with_specials:
        encoded_standard = quote(raw_pw)
        encoded_strict = quote(raw_pw, safe="")

        for enc in [encoded_standard, encoded_strict]:
            exc = Exception(f"Driver connection failed for postgresql://user:{enc}@localhost:5432/db")
            sanitized = sanitize_database_error_message(exc, raw_pw)
            assert enc not in sanitized, f"Encoded password '{enc}' leaked in '{sanitized}'"
            assert raw_pw not in sanitized, f"Raw password '{raw_pw}' leaked in '{sanitized}'"
            assert "******" in sanitized


def test_sanitize_database_error_message_redacts_plus_encoded_passwords():
    """Verify sanitize_database_error_message redacts plus-encoded passwords."""
    from urllib.parse import quote_plus
    from tests.conftest import sanitize_database_error_message

    passwords_with_spaces_and_plus = [
        "pass with spaces+plus",
        "complex+pass/with spaces:and@special%tokens",
    ]
    for raw_pw in passwords_with_spaces_and_plus:
        encoded_plus = quote_plus(raw_pw)
        exc = Exception(f"Connection failed for postgresql://user:{encoded_plus}@localhost:5432/db")
        sanitized = sanitize_database_error_message(exc, raw_pw)
        assert encoded_plus not in sanitized, f"Plus-encoded password '{encoded_plus}' leaked in '{sanitized}'"
        assert raw_pw not in sanitized, f"Raw password '{raw_pw}' leaked in '{sanitized}'"
        assert "******" in sanitized


def test_test_engine_disposal_after_normal_fixture_completion(monkeypatch):
    """Verify engine is disposed after normal fixture completion."""
    from tests.conftest import test_engine

    monkeypatch.setattr("tests.conftest.is_postgres_service_reachable", lambda h, p, timeout=1.0: True)
    mock_engine = MagicMock()
    monkeypatch.setattr("tests.conftest.create_engine", lambda *args, **kwargs: mock_engine)

    gen = test_engine.__wrapped__()
    engine = next(gen)
    assert engine == mock_engine
    assert not mock_engine.dispose.called

    # Normal completion (session teardown)
    with pytest.raises(StopIteration):
        next(gen)
    assert mock_engine.dispose.called


def test_test_engine_disposal_on_generator_exit(monkeypatch):
    """Verify engine is disposed when the fixture generator receives GeneratorExit (e.g. gen.close())."""
    from tests.conftest import test_engine

    monkeypatch.setattr("tests.conftest.is_postgres_service_reachable", lambda h, p, timeout=1.0: True)
    mock_engine = MagicMock()
    monkeypatch.setattr("tests.conftest.create_engine", lambda *args, **kwargs: mock_engine)

    gen = test_engine.__wrapped__()
    engine = next(gen)
    assert engine == mock_engine
    assert not mock_engine.dispose.called

    # Simulate GeneratorExit via gen.close()
    gen.close()
    assert mock_engine.dispose.called


def test_test_engine_disposal_when_test_raises_exception(monkeypatch):
    """Verify engine is disposed when a test raises an exception after fixture setup."""
    from tests.conftest import test_engine

    monkeypatch.setattr("tests.conftest.is_postgres_service_reachable", lambda h, p, timeout=1.0: True)
    mock_engine = MagicMock()
    monkeypatch.setattr("tests.conftest.create_engine", lambda *args, **kwargs: mock_engine)

    gen = test_engine.__wrapped__()
    engine = next(gen)
    assert engine == mock_engine
    assert not mock_engine.dispose.called

    # Simulate an unhandled exception thrown into the generator
    with pytest.raises(RuntimeError, match="Simulated test execution failure"):
        gen.throw(RuntimeError("Simulated test execution failure"))
    assert mock_engine.dispose.called


def test_test_engine_sqlite_disposal_on_generator_exit_and_exception(monkeypatch):
    """Verify SQLite engine branch is disposed on normal exit, GeneratorExit, and exception."""
    from tests.conftest import test_engine

    monkeypatch.setattr(settings, "test_database_url", "sqlite:///:memory:")

    # 1. GeneratorExit
    gen1 = test_engine.__wrapped__()
    eng1 = next(gen1)
    gen1.close()

    # 2. Exception thrown
    gen2 = test_engine.__wrapped__()
    eng2 = next(gen2)
    with pytest.raises(RuntimeError, match="SQLite test error"):
        gen2.throw(RuntimeError("SQLite test error"))


def test_test_engine_fixture_skips_when_service_unreachable(monkeypatch):
    """Verify test_engine skips tests with clear diagnostic when PostgreSQL is unreachable."""
    from tests.conftest import test_engine

    # Mock unreachable service
    monkeypatch.setattr("tests.conftest.is_postgres_service_reachable", lambda h, p, timeout=1.0: False)

    gen = test_engine.__wrapped__()
    with pytest.raises(pytest.skip.Exception, match="PostgreSQL service unreachable at localhost:5432"):
        next(gen)


def test_test_engine_fixture_fails_on_authentication_failure(monkeypatch):
    """Verify test_engine fails (never skips) on database authentication failure."""
    from tests.conftest import test_engine
    from sqlalchemy.exc import OperationalError

    # Service is reachable, but connect raises authentication error
    monkeypatch.setattr("tests.conftest.is_postgres_service_reachable", lambda h, p, timeout=1.0: True)

    mock_engine = MagicMock()
    mock_engine.connect.side_effect = OperationalError(
        "connection to server at 'localhost', port 5432 failed: FATAL: password authentication failed for user 'ledgerline'",
        None,
        None,
    )
    monkeypatch.setattr("tests.conftest.create_engine", lambda *args, **kwargs: mock_engine)

    gen = test_engine.__wrapped__()
    with pytest.raises(pytest.fail.Exception, match="PostgreSQL connection .* failed due to database or authentication misconfiguration"):
        next(gen)

    # Verify engine was disposed of safely
    assert mock_engine.dispose.called


def test_test_engine_fixture_fails_on_invalid_database(monkeypatch):
    """Verify test_engine fails (never skips) when target database does not exist."""
    from tests.conftest import test_engine
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr("tests.conftest.is_postgres_service_reachable", lambda h, p, timeout=1.0: True)

    mock_engine = MagicMock()
    mock_engine.connect.side_effect = OperationalError(
        "connection to server at 'localhost', port 5432 failed: FATAL: database 'ledgerline_test' does not exist",
        None,
        None,
    )
    monkeypatch.setattr("tests.conftest.create_engine", lambda *args, **kwargs: mock_engine)

    gen = test_engine.__wrapped__()
    with pytest.raises(pytest.fail.Exception, match="PostgreSQL connection .* failed due to database or authentication misconfiguration"):
        next(gen)

    assert mock_engine.dispose.called


def test_test_engine_fixture_sqlite_in_memory_lifecycle(monkeypatch):
    """Verify test_engine supports SQLite :memory: for isolated unit tests with clean teardown."""
    from tests.conftest import test_engine
    from sqlalchemy import text

    monkeypatch.setattr(settings, "test_database_url", "sqlite:///:memory:")

    gen = test_engine.__wrapped__()
    engine = next(gen)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1

    # Teardown
    with pytest.raises(StopIteration):
        next(gen)


def test_test_engine_fixture_connects_to_live_postgres(test_engine):
    """Verify test_engine fixture connects cleanly as migration role ledgerline_migrator."""
    from sqlalchemy import text

    with test_engine.connect() as conn:
        db_name = conn.execute(text("SELECT current_database()")).scalar()
        assert db_name == "ledgerline_test"
        current_user = conn.execute(text("SELECT current_user")).scalar()
        assert current_user == "ledgerline_migrator"


def test_app_test_engine_fixture_connects_to_live_postgres(app_test_engine):
    """Verify app_test_engine fixture connects cleanly as runtime role ledgerline_app."""
    from sqlalchemy import text

    with app_test_engine.connect() as conn:
        db_name = conn.execute(text("SELECT current_database()")).scalar()
        assert db_name == "ledgerline_test"
        current_user = conn.execute(text("SELECT current_user")).scalar()
        assert current_user == "ledgerline_app"


# ---------------------------------------------------------------------------
# FAIL-CLOSED RUNTIME DATABASE URL TESTS (Task A & Task D)
# ---------------------------------------------------------------------------


def test_runtime_url_accepts_valid_ledgerline_app():
    """Verify runtime URL validator accepts valid ledgerline_app connections."""
    for host_spec in ["localhost", "127.0.0.1", "[::1]"]:
        url1 = f"postgresql://ledgerline_app:ledgerline_app_dev@{host_spec}:5432/ledgerline"
        assert validate_runtime_database_url(url1) == url1

        url2 = f"postgresql+psycopg2://ledgerline_app:ledgerline_app_dev@{host_spec}:5432/ledgerline"
        assert validate_runtime_database_url(url2) == url2

        url_test = f"postgresql://ledgerline_app:ledgerline_app_dev@{host_spec}:5432/ledgerline_test"
        assert validate_runtime_database_url(url_test) == url_test


def test_runtime_url_accepts_sqlite_in_memory_override():
    """Verify runtime URL validator accepts SQLite in-memory for test engine overrides."""
    assert validate_runtime_database_url("sqlite:///:memory:") == "sqlite:///:memory:"


def test_runtime_url_rejects_file_based_sqlite():
    """Verify runtime URL validator rejects file-based SQLite connections."""
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*File-based SQLite"):
        validate_runtime_database_url("sqlite:///app.db")


def test_runtime_url_rejects_missing_or_empty():
    """Verify runtime URL validator fails closed on missing, empty, or whitespace URLs."""
    for empty_val in [None, "", "   ", "\t\n"]:
        with pytest.raises(ValueError, match="Application runtime database URL is empty"):
            validate_runtime_database_url(empty_val)


def test_runtime_url_rejects_malformed_urls():
    """Verify runtime URL validator fails closed on malformed connection strings."""
    with pytest.raises(ValueError, match="Invalid or malformed database URL"):
        validate_runtime_database_url("not_a_valid_url :///")


def test_runtime_url_rejects_remote_hosts():
    """Verify runtime URL validator rejects remote hosts."""
    remote_url = "postgresql://ledgerline_app:secret@192.168.1.50:5432/ledgerline"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*not an approved local host"):
        validate_runtime_database_url(remote_url)


def test_runtime_url_rejects_non_standard_ports():
    """Verify runtime URL validator rejects non-standard PostgreSQL ports."""
    bad_port_url = "postgresql://ledgerline_app:secret@localhost:5433/ledgerline"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*must use port 5432"):
        validate_runtime_database_url(bad_port_url)


def test_runtime_url_rejects_unauthorized_databases():
    """Verify runtime URL validator rejects unauthorized target databases."""
    bad_db_url = "postgresql://ledgerline_app:secret@localhost:5432/other_db"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*not an authorized runtime database"):
        validate_runtime_database_url(bad_db_url)


def test_runtime_url_rejects_privileged_roles():
    """Verify runtime URL validator strictly rejects privileged and superuser roles."""
    for privileged_role in ["ledgerline", "ledgerline_migrator", "postgres", "root", "admin"]:
        bad_role_url = f"postgresql://{privileged_role}:secret@localhost:5432/ledgerline"
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*attempted to use privileged or unauthorized role"):
            validate_runtime_database_url(bad_role_url)


def test_runtime_url_rejects_arbitrary_unapproved_roles():
    """Verify runtime URL validator rejects any user role other than ledgerline_app."""
    unapproved_url = "postgresql://attacker_user:secret@localhost:5432/ledgerline"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*must use dedicated role 'ledgerline_app'"):
        validate_runtime_database_url(unapproved_url)


def test_create_app_engine_fails_closed_when_runtime_url_missing(monkeypatch):
    """Verify create_app_engine fails closed when app_database_url is missing or empty."""
    monkeypatch.setattr(settings, "app_database_url", "")
    with pytest.raises(ValueError, match="Application runtime database URL is empty"):
        create_app_engine()


def test_create_app_engine_fails_closed_on_privileged_role(monkeypatch):
    """Verify create_app_engine fails closed when runtime URL uses privileged role."""
    monkeypatch.setattr(
        settings,
        "app_database_url",
        "postgresql://ledgerline:secret@localhost:5432/ledgerline",
    )
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*attempted to use privileged or unauthorized role"):
        create_app_engine()


def test_create_app_engine_no_unsafe_fallback_to_privileged_database_url(monkeypatch):
    """Verify create_app_engine never silently falls back to privileged database_url."""
    monkeypatch.setattr(settings, "app_database_url", None)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql://ledgerline:secret@localhost:5432/ledgerline",
    )
    with pytest.raises(ValueError, match="Application runtime database URL is empty"):
        create_app_engine()


def test_migration_database_url_rejects_runtime_role_ledgerline_app():
    """Verify validate_migration_database_url rejects runtime role ledgerline_app."""
    app_migration_url = "postgresql://ledgerline_app:secret@localhost:5432/ledgerline_test"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*cannot use runtime application role 'ledgerline_app'"):
        validate_migration_database_url(app_migration_url)


# ---------------------------------------------------------------------------
# PRODUCTION ENVIRONMENT POLICY & ALLOWLIST TESTS (PROMPT-047D Task A & Task C)
# ---------------------------------------------------------------------------


def test_production_policy_rejects_missing_hosts_allowlist():
    """Verify production runtime URL validation rejects when host allowlist is missing or empty."""
    url = "postgresql://ledgerline_app:secret@db.internal.example.com:5432/ledgerline_prod"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*Production database host allowlist is empty"):
        validate_runtime_database_url(
            url,
            app_env="production",
            allowed_hosts=[],
            allowed_databases=["ledgerline_prod"],
        )


def test_production_policy_rejects_missing_databases_allowlist():
    """Verify production runtime URL validation rejects when database allowlist is missing or empty."""
    url = "postgresql://ledgerline_app:secret@db.internal.example.com:5432/ledgerline_prod"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*Production database allowlist is empty"):
        validate_runtime_database_url(
            url,
            app_env="production",
            allowed_hosts=["db.internal.example.com"],
            allowed_databases=[],
        )


def test_production_policy_rejects_unallowlisted_host():
    """Verify production runtime URL validation rejects hosts not in explicit allowlist."""
    url = "postgresql://ledgerline_app:secret@unauthorized-db.example.com:5432/ledgerline_prod"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*not in the explicit production host allowlist"):
        validate_runtime_database_url(
            url,
            app_env="production",
            allowed_hosts=["db.internal.example.com"],
            allowed_databases=["ledgerline_prod"],
        )


def test_production_policy_rejects_unallowlisted_database():
    """Verify production runtime URL validation rejects databases not in explicit allowlist."""
    url = "postgresql://ledgerline_app:secret@db.internal.example.com:5432/unauthorized_db"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*not in the explicit production database allowlist"):
        validate_runtime_database_url(
            url,
            app_env="production",
            allowed_hosts=["db.internal.example.com"],
            allowed_databases=["ledgerline_prod"],
        )


def test_production_policy_rejects_privileged_and_migration_roles():
    """Verify production runtime URL validation rejects bootstrap, migration, and superuser roles."""
    for bad_role in ["ledgerline", "ledgerline_migrator", "postgres", "root", "admin"]:
        url = f"postgresql://{bad_role}:secret@db.internal.example.com:5432/ledgerline_prod"
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*attempted to use privileged or unauthorized role"):
            validate_runtime_database_url(
                url,
                app_env="production",
                allowed_hosts=["db.internal.example.com"],
                allowed_databases=["ledgerline_prod"],
            )


def test_production_policy_rejects_test_database_targets():
    """Verify production runtime URL validation rejects test databases under all naming variations."""
    for test_db in ["ledgerline_test", "customer_test", "test_ledgerline", "staging_test_db"]:
        url = f"postgresql://ledgerline_app:secret@db.internal.example.com:5432/{test_db}"
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*Test databases are strictly prohibited in production"):
            validate_runtime_database_url(
                url,
                app_env="production",
                allowed_hosts=["db.internal.example.com"],
                allowed_databases=[test_db, "ledgerline_prod"],
            )


def test_production_policy_rejects_sqlite():
    """Verify production runtime URL validation strictly rejects SQLite even if in-memory."""
    for sqlite_url in ["sqlite:///:memory:", "sqlite:///prod.db"]:
        with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*SQLite database.*strictly prohibited in production"):
            validate_runtime_database_url(
                sqlite_url,
                app_env="production",
                allowed_hosts=["db.internal.example.com"],
                allowed_databases=["ledgerline_prod"],
            )


def test_production_policy_accepts_explicitly_approved_configuration():
    """Verify production runtime URL validation accepts properly configured production connection."""
    url = "postgresql://ledgerline_app:ProductionPassword123!@db.internal.example.com:5432/ledgerline_prod"
    validated = validate_runtime_database_url(
        url,
        app_env="production",
        allowed_hosts=["db.internal.example.com"],
        allowed_databases=["ledgerline_prod"],
    )
    assert validated == url


def test_settings_production_fails_closed_on_missing_allowlists():
    """Verify Settings model validator fails closed in production when allowlists are omitted."""
    from backend.app.config import Settings

    valid_secret = "a" * 32

    # Missing hosts allowlist
    with pytest.raises(ValueError, match="Insecure production configuration.*db_allowed_hosts"):
        Settings(
            app_env="production",
            session_secret=valid_secret,
            db_allowed_hosts="",
            db_allowed_databases="ledgerline_prod",
        )

    # Missing databases allowlist
    with pytest.raises(ValueError, match="Insecure production configuration.*db_allowed_databases"):
        Settings(
            app_env="production",
            session_secret=valid_secret,
            db_allowed_hosts="db.internal.example.com",
            db_allowed_databases="",
        )


def test_settings_production_fails_closed_when_test_db_in_allowlist():
    """Verify Settings model validator rejects test databases in production db_allowed_databases."""
    from backend.app.config import Settings

    valid_secret = "a" * 32
    with pytest.raises(ValueError, match="Insecure production configuration.*contains test database"):
        Settings(
            app_env="production",
            session_secret=valid_secret,
            db_allowed_hosts="db.internal.example.com",
            db_allowed_databases="ledgerline_test",
        )


def test_production_migration_database_url_validation():
    """Verify validate_migration_database_url enforces production allowlists and role separation."""
    # Production migration URL accepts ledgerline_migrator with approved host and database
    prod_mig_url = "postgresql://ledgerline_migrator:secret@db.internal.example.com:5432/ledgerline_prod"
    validated = validate_migration_database_url(
        prod_mig_url,
        app_env="production",
        allowed_hosts=["db.internal.example.com"],
        allowed_databases=["ledgerline_prod"],
    )
    assert validated == prod_mig_url

    # Rejects ledgerline_app for migrations in production
    app_mig_url = "postgresql://ledgerline_app:secret@db.internal.example.com:5432/ledgerline_prod"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*cannot use runtime application role 'ledgerline_app'"):
        validate_migration_database_url(
            app_mig_url,
            app_env="production",
            allowed_hosts=["db.internal.example.com"],
            allowed_databases=["ledgerline_prod"],
        )

    # Rejects test database in production migrations
    test_mig_url = "postgresql://ledgerline_migrator:secret@db.internal.example.com:5432/ledgerline_test"
    with pytest.raises(RuntimeError, match="SAFETY VIOLATION.*Test databases are strictly prohibited in production"):
        validate_migration_database_url(
            test_mig_url,
            app_env="production",
            allowed_hosts=["db.internal.example.com"],
            allowed_databases=["ledgerline_test", "ledgerline_prod"],
        )
