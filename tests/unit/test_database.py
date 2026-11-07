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
    assert_test_database_url_safety,
    validate_migration_database_url,
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
    """Verify test_engine fixture connects cleanly to the live ledgerline_test database in Docker."""
    from sqlalchemy import text

    with test_engine.connect() as conn:
        db_name = conn.execute(text("SELECT current_database()")).scalar()
        assert db_name == "ledgerline_test"
        current_user = conn.execute(text("SELECT current_user")).scalar()
        assert current_user == "ledgerline"
