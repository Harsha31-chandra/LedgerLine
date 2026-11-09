"""
Unit tests for authentication schemas, authentication service, and session lifecycle.

Covers:
- Public user registration, email normalization, password hashing, and role defaults.
- Credential authentication, generic failures, and dummy-hash timing mitigation.
- CSPRNG session token generation and SHA-256 hash-only storage.
- Session validation (active, expired, revoked, inactive user).
- Session revocation (idempotency, preservation of audit history).
- Schema validation, extra-field forbidding, and sensitive attribute omission.
"""

from datetime import datetime, timedelta, timezone
import hashlib
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.core.exceptions import (
    AuthenticationError,
    InactiveUserError,
    SessionExpiredError,
    SessionNotFoundError,
    SessionRevokedError,
    UserAlreadyExistsError,
)
from backend.app.models.base import Base
from backend.app.models.user import User, UserRole
from backend.app.schemas.auth import (
    SessionResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from backend.app.services.auth_service import (
    DUMMY_ARGON2_HASH,
    authenticate_user,
    create_session,
    hash_session_token,
    normalize_email,
    register_user,
    revoke_all_user_sessions,
    revoke_session,
    validate_session,
)


@pytest.fixture
def db_session():
    """Provide an isolated SQLite in-memory database session with foreign keys enabled."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


# ===========================================================================
# 1. USER REGISTRATION TESTS
# ===========================================================================


def test_register_user_success(db_session):
    """Verify successful user registration with valid details."""
    user = register_user(
        db_session,
        email="testuser@example.com",
        password="SecurePassword123!",
        full_name="Test User",
    )
    assert user.id is not None
    assert user.email == "testuser@example.com"
    assert user.full_name == "Test User"
    assert user.is_active is True
    assert user.role == UserRole.HOLDER


def test_register_user_password_is_hashed_not_plaintext(db_session):
    """Verify that plaintext passwords are never persisted in the database."""
    plain_pw = "SuperSecretPassword2026!"
    user = register_user(
        db_session,
        email="hashing_test@example.com",
        password=plain_pw,
        full_name="Hash Check",
    )
    assert user.password_hash != plain_pw
    assert plain_pw not in user.password_hash
    assert user.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")


def test_register_user_default_role_is_holder(db_session):
    """Verify that public registration always assigns the HOLDER role server-side."""
    user = register_user(
        db_session,
        email="holder_role@example.com",
        password="ValidPassword123!",
        full_name="Default Role User",
    )
    assert user.role == UserRole.HOLDER
    assert user.role != UserRole.ADMIN
    assert user.role != UserRole.AUDITOR


def test_register_user_duplicate_email_rejected(db_session):
    """Verify that duplicate email registration fails safely with UserAlreadyExistsError."""
    register_user(
        db_session,
        email="duplicate@example.com",
        password="ValidPassword123!",
        full_name="First User",
    )
    with pytest.raises(UserAlreadyExistsError, match="User with email 'duplicate@example.com' already exists"):
        register_user(
            db_session,
            email="duplicate@example.com",
            password="AnotherPassword456!",
            full_name="Second User",
        )


def test_register_user_email_normalization(db_session):
    """Verify that email addresses are consistently stripped and lowercased."""
    user = register_user(
        db_session,
        email="   MiXeD.CaSe@ExAmPlE.CoM   ",
        password="ValidPassword123!",
        full_name="Normalized User",
    )
    assert user.email == "mixed.case@example.com"

    # Subsequent registration with different casing of the same email must be rejected
    with pytest.raises(UserAlreadyExistsError):
        register_user(
            db_session,
            email="MIXED.CASE@EXAMPLE.COM",
            password="DifferentPassword!",
            full_name="Conflict Check",
        )


def test_register_user_concurrent_duplicate_integrity_error_postgres_driver(db_session):
    """Verify that PostgreSQL unique constraint violation (ix_users_email) is cleanly converted."""
    rollback_mock = MagicMock(wraps=db_session.rollback)
    db_session.rollback = rollback_mock

    # Simulate psycopg2 UniqueViolation (pgcode 23505 with diag.constraint_name 'ix_users_email')
    class MockDiag:
        constraint_name = "ix_users_email"
        table_name = "users"
        message_detail = "Key (email)=(pg_dup@example.com) already exists."

    class MockPgOrig(Exception):
        pgcode = "23505"
        diag = MockDiag()

    simulated_exc = IntegrityError(
        "INSERT INTO users ...",
        {},
        MockPgOrig('duplicate key value violates unique constraint "ix_users_email"'),
    )

    with patch.object(db_session, "commit", side_effect=simulated_exc):
        with pytest.raises(UserAlreadyExistsError, match="User with email 'pg_dup@example.com' already exists"):
            register_user(
                db_session,
                email="pg_dup@example.com",
                password="ValidPassword123!",
                full_name="Postgres Duplicate",
            )

    # Rollback must be explicitly executed
    assert rollback_mock.called


def test_register_user_concurrent_duplicate_integrity_error_sqlite_driver(db_session):
    """Verify that SQLite unique constraint violation on users.email is cleanly converted."""
    rollback_mock = MagicMock(wraps=db_session.rollback)
    db_session.rollback = rollback_mock

    class MockSqliteOrig(Exception):
        sqlite_errorname = "SQLITE_CONSTRAINT_UNIQUE"
        sqlite_errorcode = 2067

    simulated_exc = IntegrityError(
        "INSERT INTO users ...",
        {},
        MockSqliteOrig("UNIQUE constraint failed: users.email"),
    )

    with patch.object(db_session, "commit", side_effect=simulated_exc):
        with pytest.raises(UserAlreadyExistsError, match="User with email 'sqlite_dup@example.com' already exists"):
            register_user(
                db_session,
                email="sqlite_dup@example.com",
                password="ValidPassword123!",
                full_name="SQLite Duplicate",
            )

    assert rollback_mock.called


def test_register_user_unrelated_postgres_unique_integrity_error_propagates(db_session):
    """Verify that unrelated PostgreSQL unique constraint violations (e.g. accounts) are re-raised."""
    rollback_mock = MagicMock(wraps=db_session.rollback)
    db_session.rollback = rollback_mock

    class MockDiag:
        constraint_name = "ix_accounts_account_number"
        table_name = "accounts"
        message_detail = "Key (account_number)=(ACC-123) already exists."

    class MockPgOrig(Exception):
        pgcode = "23505"
        diag = MockDiag()

    simulated_exc = IntegrityError(
        "INSERT INTO accounts ...",
        {},
        MockPgOrig('duplicate key value violates unique constraint "ix_accounts_account_number"'),
    )

    with patch.object(db_session, "commit", side_effect=simulated_exc):
        with pytest.raises(IntegrityError):
            register_user(
                db_session,
                email="unrelated_uniq@example.com",
                password="ValidPassword123!",
                full_name="Unrelated Unique",
            )

    assert rollback_mock.called


def test_register_user_unrelated_check_integrity_error_propagates(db_session):
    """Verify that unrelated check constraint violations (e.g. ck_users_role_valid) are re-raised."""
    rollback_mock = MagicMock(wraps=db_session.rollback)
    db_session.rollback = rollback_mock

    class MockPgOrig(Exception):
        pgcode = "23514"  # PostgreSQL check_violation code

    simulated_exc = IntegrityError(
        "INSERT INTO users ...",
        {},
        MockPgOrig('new row violates check constraint "ck_users_role_valid"'),
    )

    with patch.object(db_session, "commit", side_effect=simulated_exc):
        with pytest.raises(IntegrityError):
            register_user(
                db_session,
                email="unrelated_check@example.com",
                password="ValidPassword123!",
                full_name="Unrelated Check User",
            )

    assert rollback_mock.called


def test_register_user_unrelated_sqlite_integrity_error_propagates(db_session):
    """Verify that unrelated SQLite constraint violations (e.g. accounts.account_number or check) are re-raised."""
    rollback_mock = MagicMock(wraps=db_session.rollback)
    db_session.rollback = rollback_mock

    class MockSqliteOrig(Exception):
        sqlite_errorname = "SQLITE_CONSTRAINT_UNIQUE"
        sqlite_errorcode = 2067

    simulated_exc = IntegrityError(
        "INSERT INTO accounts ...",
        {},
        MockSqliteOrig("UNIQUE constraint failed: accounts.account_number"),
    )

    with patch.object(db_session, "commit", side_effect=simulated_exc):
        with pytest.raises(IntegrityError):
            register_user(
                db_session,
                email="unrelated_sqlite@example.com",
                password="ValidPassword123!",
                full_name="Unrelated SQLite User",
            )

    assert rollback_mock.called


def test_register_user_empty_or_whitespace_name_rejected(db_session):
    """Verify that empty full names are rejected."""
    with pytest.raises(ValueError, match="Full name cannot be empty"):
        register_user(
            db_session,
            email="valid@example.com",
            password="ValidPassword123!",
            full_name="   ",
        )


def test_register_user_cannot_assign_privileged_role_via_schema():
    """Verify that UserRegisterRequest forbids extra fields like 'role' to prevent privilege escalation."""
    with pytest.raises(ValidationError) as exc_info:
        UserRegisterRequest(
            email="attacker@example.com",
            password="Password123!",
            full_name="Attacker",
            role="ADMIN",  # Forbidden client-injected field
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


# ===========================================================================
# 2. USER AUTHENTICATION TESTS
# ===========================================================================


def test_authenticate_user_valid_credentials_succeeds(db_session):
    """Verify that valid email and password authenticate successfully."""
    register_user(
        db_session,
        email="auth_success@example.com",
        password="CorrectPassword123!",
        full_name="Success User",
    )
    user = authenticate_user(
        db_session,
        email="auth_success@example.com",
        password="CorrectPassword123!",
    )
    assert user is not None
    assert user.email == "auth_success@example.com"


def test_authenticate_user_incorrect_password_fails(db_session):
    """Verify that an incorrect password raises AuthenticationError."""
    register_user(
        db_session,
        email="wrong_pass@example.com",
        password="RealPassword123!",
        full_name="Wrong Pass User",
    )
    with pytest.raises(AuthenticationError, match="Invalid email or password"):
        authenticate_user(
            db_session,
            email="wrong_pass@example.com",
            password="WrongPassword999!",
        )


def test_authenticate_user_nonexistent_email_fails(db_session):
    """Verify that non-existent email raises generic AuthenticationError."""
    with pytest.raises(AuthenticationError, match="Invalid email or password"):
        authenticate_user(
            db_session,
            email="does_not_exist@example.com",
            password="SomePassword123!",
        )


def test_authenticate_user_dummy_hash_verification_called_for_nonexistent_user(db_session):
    """Verify that dummy Argon2id verification executes when an email does not exist."""
    with patch("backend.app.services.auth_service.verify_password", wraps=lambda p, h: False) as mock_verify:
        with pytest.raises(AuthenticationError):
            authenticate_user(
                db_session,
                email="ghost@example.com",
                password="TestPassword123!",
            )
        # Must verify against the precomputed dummy hash to mitigate timing-based account enumeration
        mock_verify.assert_called_once_with("TestPassword123!", DUMMY_ARGON2_HASH)


def test_authenticate_user_inactive_user_fails(db_session):
    """Verify that deactivated users are rejected with InactiveUserError."""
    user = register_user(
        db_session,
        email="inactive@example.com",
        password="ValidPassword123!",
        full_name="Inactive User",
    )
    user.is_active = False
    db_session.commit()

    with pytest.raises(InactiveUserError, match="User account is inactive"):
        authenticate_user(
            db_session,
            email="inactive@example.com",
            password="ValidPassword123!",
        )


def test_authenticate_user_unexpected_error_not_swallowed(db_session):
    """Verify that unexpected system exceptions (e.g. database/memory crash) are not silently swallowed."""
    register_user(
        db_session,
        email="crash_test@example.com",
        password="ValidPassword123!",
        full_name="Crash Test",
    )
    with patch("backend.app.services.auth_service.verify_password", side_effect=RuntimeError("Internal system fault")):
        with pytest.raises(RuntimeError, match="Internal system fault"):
            authenticate_user(
                db_session,
                email="crash_test@example.com",
                password="ValidPassword123!",
            )


# ===========================================================================
# 3. SESSION CREATION TESTS
# ===========================================================================


def test_create_session_token_is_secure_and_unpredictable(db_session):
    """Verify that session tokens are cryptographically random, distinct, and 256 bits."""
    user = register_user(
        db_session,
        email="session_user@example.com",
        password="ValidPassword123!",
        full_name="Session User",
    )
    res1 = create_session(db_session, user)
    res2 = create_session(db_session, user)

    # Must generate distinct unpredictable tokens
    assert res1.raw_token != res2.raw_token
    # 32 bytes URL-safe base64 is 43 characters (~256 bits entropy)
    assert len(res1.raw_token) >= 43
    assert len(res2.raw_token) >= 43


def test_create_session_stores_only_sha256_digest(db_session):
    """Verify that database stores only the 64-character SHA-256 digest of the token."""
    user = register_user(
        db_session,
        email="digest_check@example.com",
        password="ValidPassword123!",
        full_name="Digest Check",
    )
    result = create_session(db_session, user)

    expected_hash = hashlib.sha256(result.raw_token.encode("utf-8")).hexdigest()
    assert result.session.token_hash == expected_hash
    assert len(result.session.token_hash) == 64


def test_create_session_raw_token_not_stored_in_database(db_session):
    """Verify that the raw token is never written to the session record."""
    user = register_user(
        db_session,
        email="raw_check@example.com",
        password="ValidPassword123!",
        full_name="Raw Check",
    )
    result = create_session(db_session, user)

    assert result.raw_token != result.session.token_hash
    assert result.raw_token not in str(result.session.__dict__)


def test_create_session_expiry_calculated_correctly_with_utc(db_session):
    """Verify that session expiry timestamp is calculated correctly using timezone-aware UTC."""
    user = register_user(
        db_session,
        email="ttl_check@example.com",
        password="ValidPassword123!",
        full_name="TTL Check",
    )
    now_before = datetime.now(timezone.utc)
    result = create_session(db_session, user, ttl_minutes=60)
    now_after = datetime.now(timezone.utc)

    # Expiration must be approximately 60 minutes after creation (normalize naive SQLite timestamp)
    expires_at = result.session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    assert expires_at >= now_before + timedelta(minutes=59)
    assert expires_at <= now_after + timedelta(minutes=61)
    assert result.session.revoked_at is None


def test_create_session_rejects_non_positive_or_invalid_ttl(db_session):
    """Verify that create_session rejects zero, negative, boolean, and non-integer TTL values."""
    user = register_user(
        db_session,
        email="ttl_invalid@example.com",
        password="ValidPassword123!",
        full_name="TTL Invalid Check",
    )

    invalid_ttls = [0, -1, -60, False, True, "60", 3.14, 14.0]
    for bad_ttl in invalid_ttls:
        with pytest.raises(ValueError, match="Session TTL must be a positive integer greater than zero"):
            create_session(db_session, user, ttl_minutes=bad_ttl)


def test_create_session_valid_boundary_ttl(db_session):
    """Verify that create_session accepts minimum valid boundary TTL (1 minute)."""
    user = register_user(
        db_session,
        email="ttl_boundary@example.com",
        password="ValidPassword123!",
        full_name="TTL Boundary Check",
    )
    now_before = datetime.now(timezone.utc)
    result = create_session(db_session, user, ttl_minutes=1)
    now_after = datetime.now(timezone.utc)

    expires_at = result.session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    assert expires_at >= now_before + timedelta(seconds=55)
    assert expires_at <= now_after + timedelta(seconds=65)


def test_create_session_inactive_user_fails(db_session):
    """Verify that sessions cannot be created for inactive users."""
    user = register_user(
        db_session,
        email="inactive_sess@example.com",
        password="ValidPassword123!",
        full_name="Inactive Session",
    )
    user.is_active = False
    db_session.commit()

    with pytest.raises(InactiveUserError, match="Cannot create a session for an inactive user"):
        create_session(db_session, user)


# ===========================================================================
# 4. SESSION VALIDATION TESTS
# ===========================================================================


def test_validate_session_valid_succeeds(db_session):
    """Verify that an active, unexpired session validates successfully."""
    user = register_user(
        db_session,
        email="validate_ok@example.com",
        password="ValidPassword123!",
        full_name="Validate OK",
    )
    session_res = create_session(db_session, user)

    session, validated_user = validate_session(db_session, session_res.raw_token)
    assert session.id == session_res.session.id
    assert validated_user.id == user.id
    assert validated_user.email == "validate_ok@example.com"


def test_validate_session_unknown_token_fails(db_session):
    """Verify that an unknown or fabricated token raises SessionNotFoundError."""
    with pytest.raises(SessionNotFoundError, match="Session not found"):
        validate_session(db_session, "nonexistent_token_string_1234567890")


def test_validate_session_expired_fails(db_session):
    """Verify that an expired session raises SessionExpiredError."""
    user = register_user(
        db_session,
        email="expired@example.com",
        password="ValidPassword123!",
        full_name="Expired User",
    )
    # Create valid session, then manually expire it in database
    session_res = create_session(db_session, user, ttl_minutes=60)
    session_res.session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()

    with pytest.raises(SessionExpiredError, match="Session has expired"):
        validate_session(db_session, session_res.raw_token)


def test_validate_session_revoked_fails(db_session):
    """Verify that an explicitly revoked session raises SessionRevokedError."""
    user = register_user(
        db_session,
        email="revoked_val@example.com",
        password="ValidPassword123!",
        full_name="Revoked Val",
    )
    session_res = create_session(db_session, user)
    revoke_session(db_session, session_res.raw_token)

    with pytest.raises(SessionRevokedError, match="Session has been revoked"):
        validate_session(db_session, session_res.raw_token)


def test_validate_session_inactive_user_fails(db_session):
    """Verify that a session belonging to a deactivated user is rejected."""
    user = register_user(
        db_session,
        email="deactivated_sess@example.com",
        password="ValidPassword123!",
        full_name="Deactivated Sess",
    )
    session_res = create_session(db_session, user)

    # Deactivate the user after session issuance
    user.is_active = False
    db_session.commit()

    with pytest.raises(InactiveUserError, match="User account is inactive"):
        validate_session(db_session, session_res.raw_token)


def test_validate_session_empty_or_bad_token_fails(db_session):
    """Verify that invalid token formats fail closed safely."""
    with pytest.raises(SessionNotFoundError):
        validate_session(db_session, "")
    with pytest.raises(SessionNotFoundError):
        validate_session(db_session, None)


# ===========================================================================
# 5. SESSION REVOCATION TESTS
# ===========================================================================


def test_revoke_session_active_succeeds(db_session):
    """Verify that an active session can be revoked and records revocation time."""
    user = register_user(
        db_session,
        email="rev_active@example.com",
        password="ValidPassword123!",
        full_name="Rev Active",
    )
    session_res = create_session(db_session, user)
    assert session_res.session.revoked_at is None

    revoked_session = revoke_session(db_session, session_res.raw_token)
    assert revoked_session.revoked_at is not None
    assert isinstance(revoked_session.revoked_at, datetime)


def test_revoke_session_remains_invalid_and_idempotent(db_session):
    """Verify that repeated revocation is idempotent and does not alter the original timestamp."""
    user = register_user(
        db_session,
        email="idempotent_rev@example.com",
        password="ValidPassword123!",
        full_name="Idempotent Rev",
    )
    session_res = create_session(db_session, user)

    first_rev = revoke_session(db_session, session_res.raw_token)
    first_time = first_rev.revoked_at

    second_rev = revoke_session(db_session, session_res.raw_token)
    assert second_rev.revoked_at == first_time


def test_revoke_session_unknown_token_fails(db_session):
    """Verify that revoking an unknown token raises SessionNotFoundError."""
    with pytest.raises(SessionNotFoundError, match="Session not found"):
        revoke_session(db_session, "completely_unknown_token")


def test_revoke_all_user_sessions(db_session):
    """Verify that all active sessions for a user can be revoked at once."""
    user = register_user(
        db_session,
        email="multi_sess@example.com",
        password="ValidPassword123!",
        full_name="Multi Session",
    )
    s1 = create_session(db_session, user)
    s2 = create_session(db_session, user)
    s3 = create_session(db_session, user)

    count = revoke_all_user_sessions(db_session, user.id)
    assert count == 3

    # All three sessions must now be rejected
    for s in [s1, s2, s3]:
        with pytest.raises(SessionRevokedError):
            validate_session(db_session, s.raw_token)


# ===========================================================================
# 6. SCHEMA VALIDATION TESTS
# ===========================================================================


def test_user_register_request_schema_validation():
    """Verify UserRegisterRequest input rules and validation."""
    # Valid registration
    req = UserRegisterRequest(
        email=" Valid.Email@Domain.COM ",
        password="ValidPassword123!",
        full_name="  Full Name  ",
    )
    assert req.email == "valid.email@domain.com"
    assert req.full_name == "Full Name"

    # Password policy: No arbitrary 8-character minimum is enforced;
    # short passwords (within safe boundary min_length=1) are accepted by schema
    req_short = UserRegisterRequest(
        email="valid@example.com",
        password="short",
        full_name="Valid Name",
    )
    assert req_short.password == "short"

    # Single character password boundary (min_length=1)
    req_single = UserRegisterRequest(
        email="valid@example.com",
        password="p",
        full_name="Valid Name",
    )
    assert req_single.password == "p"

    # Empty password rejected (min_length=1)
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            email="valid@example.com",
            password="",
            full_name="Valid Name",
        )

    # Password exceeding max boundary (128 characters) rejected
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            email="valid@example.com",
            password="A" * 129,
            full_name="Valid Name",
        )

    # Invalid email format
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            email="invalid_email_format",
            password="ValidPassword123!",
            full_name="Valid Name",
        )


def test_user_login_request_schema_validation():
    """Verify UserLoginRequest input rules and validation."""
    req = UserLoginRequest(
        email=" Login.User@Example.COM ",
        password="SecretPassword!",
    )
    assert req.email == "login.user@example.com"
    assert req.password == "SecretPassword!"

    # Invalid email
    with pytest.raises(ValidationError):
        UserLoginRequest(email="not-an-email", password="pw")


def test_user_response_excludes_password_hash(db_session):
    """Verify that UserResponse schema serialization never exposes password_hash."""
    user = register_user(
        db_session,
        email="schema_leak_check@example.com",
        password="ValidPassword123!",
        full_name="Schema Leak Check",
    )
    resp = UserResponse.model_validate(user)
    dumped = resp.model_dump()

    assert "password_hash" not in dumped
    assert "password" not in dumped
    assert dumped["email"] == "schema_leak_check@example.com"
    assert dumped["role"] == "HOLDER"


def test_session_response_excludes_token_hash(db_session):
    """Verify that SessionResponse schema serialization never exposes internal token_hash."""
    user = register_user(
        db_session,
        email="sess_resp@example.com",
        password="ValidPassword123!",
        full_name="Sess Resp Check",
    )
    session_res = create_session(db_session, user)
    resp = SessionResponse.model_validate(session_res.session)
    dumped = resp.model_dump()

    assert "token_hash" not in dumped
    assert "raw_token" not in dumped
    assert dumped["user_id"] == user.id


# ===========================================================================
# 7. SETTINGS AND ENVIRONMENT CONFIGURATION TESTS
# ===========================================================================


def test_settings_session_ttl_validation():
    """Verify that Settings strictly validates session_ttl_minutes to accept only positive integers."""
    # Positive integer values pass
    s1 = Settings(session_ttl_minutes=1)
    assert s1.session_ttl_minutes == 1

    s1440 = Settings(session_ttl_minutes=1440)
    assert s1440.session_ttl_minutes == 1440

    # Valid integer strings (from environment variables) pass
    s_env1 = Settings(session_ttl_minutes="1")
    assert s_env1.session_ttl_minutes == 1

    s_env1440 = Settings(session_ttl_minutes="1440")
    assert s_env1440.session_ttl_minutes == 1440

    # Booleans explicitly rejected
    with pytest.raises(ValidationError, match="session_ttl_minutes cannot be a boolean"):
        Settings(session_ttl_minutes=True)

    with pytest.raises(ValidationError, match="session_ttl_minutes cannot be a boolean"):
        Settings(session_ttl_minutes=False)

    # Floats explicitly rejected (both fractional and whole numbers)
    with pytest.raises(ValidationError, match="session_ttl_minutes cannot be a float"):
        Settings(session_ttl_minutes=14.5)

    with pytest.raises(ValidationError, match="session_ttl_minutes cannot be a float"):
        Settings(session_ttl_minutes=14.0)

    # Zero rejected (both int and string)
    with pytest.raises(ValidationError, match="session_ttl_minutes must be a positive integer greater than zero"):
        Settings(session_ttl_minutes=0)

    with pytest.raises(ValidationError, match="session_ttl_minutes must be a positive integer greater than zero"):
        Settings(session_ttl_minutes="0")

    # Negative values rejected (both int and string)
    with pytest.raises(ValidationError, match="session_ttl_minutes must be a positive integer greater than zero"):
        Settings(session_ttl_minutes=-10)

    with pytest.raises(ValidationError, match="session_ttl_minutes must be a valid positive integer string"):
        Settings(session_ttl_minutes="-10")

    # Non-integer strings rejected
    with pytest.raises(ValidationError, match="session_ttl_minutes must be a valid positive integer string"):
        Settings(session_ttl_minutes="14.0")

    with pytest.raises(ValidationError, match="session_ttl_minutes must be a valid positive integer string"):
        Settings(session_ttl_minutes="true")

    with pytest.raises(ValidationError, match="session_ttl_minutes must be a valid positive integer string"):
        Settings(session_ttl_minutes="abc")


def test_settings_production_session_secret_safeguards():
    """Verify that production environment fails closed if session_secret is insecure."""
    # Production with known placeholder rejected
    with pytest.raises(ValidationError, match="Insecure production configuration"):
        Settings(
            app_env="production",
            session_secret="change-me-to-a-random-string",
        )

    # Production with short secret (<32 chars) rejected
    with pytest.raises(ValidationError, match="Insecure production configuration"):
        Settings(
            app_env="production",
            session_secret="short-secret-under-32-chars",
        )

    # Production with valid 32+ character secret accepted
    prod_settings = Settings(
        app_env="production",
        session_secret="a" * 32,
    )
    assert prod_settings.app_env == "production"
    assert prod_settings.session_secret == "a" * 32

    # Production alias 'prod' behaves identically
    with pytest.raises(ValidationError, match="Insecure production configuration"):
        Settings(
            app_env="prod",
            session_secret="change-me-to-a-random-string",
        )

    # Development allows default placeholder secret
    dev_settings = Settings(
        app_env="development",
        session_secret="change-me-to-a-random-string",
    )
    assert dev_settings.session_secret == "change-me-to-a-random-string"
