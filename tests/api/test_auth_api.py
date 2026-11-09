"""
End-to-end integration and API unit tests for LedgerLine HTTP authentication endpoints.

Covers:
- POST /auth/register: Public registration, HOLDER role assignment, duplicate email, invalid payload.
- POST /auth/login: Credential authentication, generic error uniformity, inactive account handling,
  Set-Cookie HTTP-only attributes, and absence of raw tokens/hashes in response JSON.
- GET /auth/me: Session validation (active, missing cookie, invalid token, expired, revoked, inactive user).
- POST /auth/logout: Revocation in database, cookie deletion, and idempotent behavior.
- CSRF Protection: Rejection of cross-origin requests, untrusted referers, missing origins on mutations,
  and allowance of legitimate origins and safe GET methods.
- Rate Limiting: SlowAPI rate-limit enforcement returning HTTP 429 on registration and login.
"""

from datetime import datetime, timedelta, timezone
from typing import Generator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.deps import get_db
from backend.app.config import settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security import hash_password
from backend.app.main import app
from backend.app.models.base import Base
from backend.app.models.user import User, UserRole
from backend.app.services.auth_service import create_session, register_user

# Trusted origin matching default configured frontend origin
TRUSTED_ORIGIN = "http://localhost:5173"
TRUSTED_HEADERS = {"Origin": TRUSTED_ORIGIN}


@pytest.fixture
def db_engine():
    """Provide an isolated in-memory SQLite engine with foreign keys and thread sharing enabled."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """Provide an isolated database session for direct test assertions."""
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine) -> Generator[TestClient, None, None]:
    """Provide a TestClient with injected test database session factory and cleared rate limits."""
    limiter._storage.reset()
    session_factory = sessionmaker(
        bind=db_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    def _override_get_db():
        session = session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    limiter._storage.reset()


# ===========================================================================
# 1. REGISTRATION ENDPOINT TESTS (POST /auth/register)
# ===========================================================================


def test_register_success(client: TestClient):
    """Verify successful public registration returns HTTP 201 and safe UserResponse."""
    payload = {
        "email": "newuser@example.com",
        "password": "ValidPassword123!",
        "full_name": "New LedgerLine User",
    }
    response = client.post("/auth/register", json=payload, headers=TRUSTED_HEADERS)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["full_name"] == "New LedgerLine User"
    assert data["role"] == "HOLDER"
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data

    # Verify sensitive fields are never exposed in response JSON
    assert "password" not in data
    assert "password_hash" not in data
    assert "token" not in data
    assert "token_hash" not in data


def test_register_duplicate_email_rejected(client: TestClient):
    """Verify registering an existing email returns HTTP 409 Conflict."""
    payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "full_name": "Original User",
    }
    r1 = client.post("/auth/register", json=payload, headers=TRUSTED_HEADERS)
    assert r1.status_code == 201

    # Second attempt with same email (even with different casing/whitespace)
    payload_dup = {
        "email": "  DUPLICATE@example.com  ",
        "password": "DifferentPassword123!",
        "full_name": "Second User",
    }
    r2 = client.post("/auth/register", json=payload_dup, headers=TRUSTED_HEADERS)
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"].lower()


def test_register_invalid_input_rejected(client: TestClient):
    """Verify invalid payloads return HTTP 422 Unprocessable Entity."""
    # Bad email format
    r_bad_email = client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "pass", "full_name": "User"},
        headers=TRUSTED_HEADERS,
    )
    assert r_bad_email.status_code == 422

    # Empty password
    r_empty_pw = client.post(
        "/auth/register",
        json={"email": "valid@example.com", "password": "", "full_name": "User"},
        headers=TRUSTED_HEADERS,
    )
    assert r_empty_pw.status_code == 422

    # Missing full_name
    r_no_name = client.post(
        "/auth/register",
        json={"email": "valid@example.com", "password": "pass"},
        headers=TRUSTED_HEADERS,
    )
    assert r_no_name.status_code == 422


def test_register_cannot_inject_privileged_role(client: TestClient):
    """Verify that clients cannot inject a privileged role like ADMIN."""
    payload = {
        "email": "attacker@example.com",
        "password": "Password123!",
        "full_name": "Attacker",
        "role": "ADMIN",  # Forbidden client-injected field
    }
    response = client.post("/auth/register", json=payload, headers=TRUSTED_HEADERS)
    assert response.status_code == 422
    assert "Extra inputs are not permitted" in response.text


# ===========================================================================
# 2. LOGIN ENDPOINT TESTS (POST /auth/login)
# ===========================================================================


def test_login_success_sets_http_only_cookie(client: TestClient, db_session: Session):
    """Verify valid login sets secure HTTP-only cookie and returns UserResponse."""
    register_user(
        db_session,
        email="login_user@example.com",
        password="MySecretPassword123!",
        full_name="Login User",
    )

    payload = {
        "email": "login_user@example.com",
        "password": "MySecretPassword123!",
    }
    response = client.post("/auth/login", json=payload, headers=TRUSTED_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "login_user@example.com"
    assert data["role"] == "HOLDER"

    # Verify sensitive data is absent from JSON response
    assert "password" not in data
    assert "password_hash" not in data
    assert "token" not in data
    assert "raw_token" not in data
    assert "token_hash" not in data

    # Verify session cookie was set with required security attributes
    assert settings.session_cookie_name in response.cookies
    cookie_header = response.headers.get("set-cookie", "")
    assert f"{settings.session_cookie_name}=" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()
    assert "path=/" in cookie_header.lower()


def test_login_invalid_password_returns_generic_error(client: TestClient, db_session: Session):
    """Verify incorrect password returns generic HTTP 401 error."""
    register_user(
        db_session,
        email="real_user@example.com",
        password="RealPassword123!",
        full_name="Real User",
    )

    payload = {"email": "real_user@example.com", "password": "WrongPassword!"}
    response = client.post("/auth/login", json=payload, headers=TRUSTED_HEADERS)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert settings.session_cookie_name not in response.cookies


def test_login_unknown_email_returns_identical_generic_error(client: TestClient):
    """Verify nonexistent account returns exact same generic HTTP 401 error (preventing enumeration)."""
    payload = {"email": "nonexistent@example.com", "password": "SomePassword123!"}
    response = client.post("/auth/login", json=payload, headers=TRUSTED_HEADERS)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert settings.session_cookie_name not in response.cookies


def test_login_inactive_user_rejected(client: TestClient, db_session: Session):
    """Verify deactivated user account receives HTTP 403 Forbidden upon login."""
    user = register_user(
        db_session,
        email="inactive@example.com",
        password="ValidPassword123!",
        full_name="Inactive User",
    )
    user.is_active = False
    db_session.commit()

    payload = {"email": "inactive@example.com", "password": "ValidPassword123!"}
    response = client.post("/auth/login", json=payload, headers=TRUSTED_HEADERS)

    assert response.status_code == 403
    assert response.json() == {"detail": "User account is inactive"}
    assert settings.session_cookie_name not in response.cookies


# ===========================================================================
# 3. SESSION AND CURRENT USER TESTS (GET /auth/me & POST /auth/logout)
# ===========================================================================


def test_get_me_valid_session_success(client: TestClient, db_session: Session):
    """Verify GET /auth/me with active session cookie returns the authenticated user."""
    user = register_user(
        db_session,
        email="me_test@example.com",
        password="ValidPassword123!",
        full_name="Me User",
    )
    sess_res = create_session(db_session, user)

    # Set cookie on test client
    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
    response = client.get("/auth/me")

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me_test@example.com"
    assert data["id"] == str(user.id)
    assert data["role"] == "HOLDER"
    assert "password_hash" not in data


def test_get_me_missing_cookie_rejected(client: TestClient):
    """Verify GET /auth/me without session cookie returns HTTP 401 Unauthorized."""
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_get_me_invalid_token_rejected(client: TestClient):
    """Verify GET /auth/me with an unknown or forged token returns HTTP 401 Unauthorized."""
    client.cookies.set(settings.session_cookie_name, "forged_unknown_token_value_12345")
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid session token"}


def test_get_me_expired_session_rejected(client: TestClient, db_session: Session):
    """Verify GET /auth/me with an expired session returns HTTP 401 Unauthorized."""
    user = register_user(
        db_session,
        email="expired_me@example.com",
        password="ValidPassword123!",
        full_name="Expired User",
    )
    sess_res = create_session(db_session, user)

    # Manually backdate expiration in the database
    sess_res.session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()

    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Session has expired"}


def test_get_me_revoked_session_rejected(client: TestClient, db_session: Session):
    """Verify GET /auth/me with a revoked session returns HTTP 401 Unauthorized."""
    user = register_user(
        db_session,
        email="revoked_me@example.com",
        password="ValidPassword123!",
        full_name="Revoked User",
    )
    sess_res = create_session(db_session, user)
    sess_res.session.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Session has been revoked"}


def test_get_me_inactive_user_rejected(client: TestClient, db_session: Session):
    """Verify GET /auth/me for a user deactivated after login returns HTTP 403 Forbidden."""
    user = register_user(
        db_session,
        email="deact_me@example.com",
        password="ValidPassword123!",
        full_name="Deactivated User",
    )
    sess_res = create_session(db_session, user)

    # Deactivate account after session creation
    user.is_active = False
    db_session.commit()

    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
    response = client.get("/auth/me")

    assert response.status_code == 403
    assert response.json() == {"detail": "User account is inactive"}


def test_logout_revokes_session_and_clears_cookie(client: TestClient, db_session: Session):
    """Verify POST /auth/logout revokes session in DB and clears cookie with proper attributes."""
    user = register_user(
        db_session,
        email="logout_user@example.com",
        password="ValidPassword123!",
        full_name="Logout User",
    )
    sess_res = create_session(db_session, user)

    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
    response = client.post("/auth/logout", headers=TRUSTED_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"detail": "Successfully logged out"}

    # Cookie must be cleared in Set-Cookie header with matching security attributes
    cookie_header = response.headers.get("set-cookie", "")
    assert f"{settings.session_cookie_name}=" in cookie_header
    assert (
        f'{settings.session_cookie_name}=""' in cookie_header
        or f"{settings.session_cookie_name}=;" in cookie_header
        or "max-age=0" in cookie_header.lower()
    )
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()
    assert "path=/" in cookie_header.lower()

    # Session in DB must now have revoked_at timestamp
    db_session.refresh(sess_res.session)
    assert sess_res.session.revoked_at is not None

    # Subsequent GET /auth/me using that token must fail
    r_after = client.get("/auth/me")
    assert r_after.status_code == 401


def test_logout_idempotent_when_unauthenticated(client: TestClient):
    """Verify POST /auth/logout succeeds idempotently even if no session was present."""
    response = client.post("/auth/logout", headers=TRUSTED_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"detail": "Successfully logged out"}


# ===========================================================================
# 4. CSRF AND BROWSER SECURITY TESTS
# ===========================================================================


def test_csrf_untrusted_origin_rejected(client: TestClient):
    """Verify state-changing POST requests from an untrusted origin return HTTP 403."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "https://malicious-attacker.com"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted origin"}


def test_csrf_missing_origin_and_referer_rejected(client: TestClient):
    """Verify state-changing POST requests without Origin and Referer return HTTP 403."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={},  # Missing both Origin and Referer
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: missing origin and referer"}


def test_csrf_untrusted_referer_rejected(client: TestClient):
    """Verify state-changing POST requests with an untrusted Referer return HTTP 403."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Referer": "https://malicious-attacker.com/evil-page"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted referer"}


def test_csrf_trusted_referer_allowed_when_origin_missing(client: TestClient):
    """Verify state-changing POST requests with a trusted Referer pass CSRF verification."""
    response = client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "pass"},
        headers={"Referer": "http://localhost:5173/login"},
    )
    # Passes CSRF, fails credentials (401)
    assert response.status_code == 401


def test_csrf_safe_methods_bypass_origin_check(client: TestClient):
    """Verify read-only safe methods (GET) are not blocked by CSRF checks."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "ledgerline"}


def test_csrf_host_header_manipulation_rejected(client: TestClient, db_session: Session):
    """Verify that spoofing Host and Origin headers cannot bypass CSRF protection."""
    user = register_user(
        db_session,
        email="host_spoof@example.com",
        password="ValidPassword123!",
        full_name="Host Spoof User",
    )
    sess_res = create_session(db_session, user)
    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)

    # Attacker attempts Host-header origin poisoning
    response = client.post(
        "/auth/logout",
        headers={"Host": "evil.com", "Origin": "http://evil.com"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted origin"}

    # Confirm the rejected request did NOT perform its intended state change
    db_session.refresh(sess_res.session)
    assert sess_res.session.revoked_at is None

    # Confirm the session remains active
    r_me = client.get("/auth/me")
    assert r_me.status_code == 200
    assert r_me.json()["email"] == "host_spoof@example.com"


def test_csrf_malformed_referer_rejected(client: TestClient):
    """Verify state-changing requests with malformed Referer return HTTP 403, not HTTP 500."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Referer": "http://[invalid-bracket"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted referer"}


def test_csrf_logout_untrusted_origin_rejected(client: TestClient, db_session: Session):
    """Verify POST /auth/logout with untrusted cross-origin Origin returns HTTP 403 without revoking."""
    user = register_user(
        db_session,
        email="logout_csrf@example.com",
        password="ValidPassword123!",
        full_name="Logout CSRF User",
    )
    sess_res = create_session(db_session, user)
    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)

    response = client.post(
        "/auth/logout",
        headers={"Origin": "https://untrusted-attacker.org"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted origin"}

    # Verify session in DB was NOT revoked by the rejected request
    db_session.refresh(sess_res.session)
    assert sess_res.session.revoked_at is None


def test_csrf_origin_null_rejected(client: TestClient):
    """Verify opaque Origin: null (e.g. from sandboxed iframes or data URLs) returns HTTP 403."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "null"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted origin"}


def test_csrf_malformed_origin_rejected(client: TestClient):
    """Verify malformed Origin values return HTTP 403 without producing unhandled 500 exceptions."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://[invalid-bracket"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted origin"}


def test_csrf_untrusted_origin_with_trusted_referer_rejected(client: TestClient):
    """Verify that an untrusted Origin cannot be bypassed by providing a trusted Referer."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={
            "Origin": "https://evil.com",
            "Referer": "http://localhost:5173/login",
        },
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted origin"}


def test_csrf_referer_missing_hostname_rejected(client: TestClient):
    """Verify Referer headers with missing hostname or non-http scheme return HTTP 403."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Referer": "not-a-valid-url"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted referer"}


def test_csrf_origin_non_integer_port_rejected(client: TestClient):
    """Verify state-changing requests with non-integer Origin ports return HTTP 403."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://localhost:abc"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted origin"}


def test_csrf_origin_out_of_range_port_rejected(client: TestClient):
    """Verify state-changing requests with out-of-range Origin ports return HTTP 403."""
    # Port > 65535
    r1 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://localhost:99999"},
    )
    assert r1.status_code == 403
    assert r1.json() == {"detail": "CSRF verification failed: untrusted origin"}

    # HTTPS port > 65535
    r2 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "https://localhost:99999"},
    )
    assert r2.status_code == 403
    assert r2.json() == {"detail": "CSRF verification failed: untrusted origin"}

    # Port 0 (reserved / invalid)
    r3 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://localhost:0"},
    )
    assert r3.status_code == 403
    assert r3.json() == {"detail": "CSRF verification failed: untrusted origin"}

    # Empty port specification (trailing colon)
    r4 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://localhost:"},
    )
    assert r4.status_code == 403
    assert r4.json() == {"detail": "CSRF verification failed: untrusted origin"}


def test_csrf_referer_non_integer_port_rejected(client: TestClient):
    """Verify state-changing requests with non-integer Referer ports return HTTP 403."""
    response = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Referer": "http://localhost:abc/login"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF verification failed: untrusted referer"}


def test_csrf_referer_out_of_range_port_rejected(client: TestClient):
    """Verify state-changing requests with out-of-range Referer ports return HTTP 403."""
    # Port > 65535
    r1 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Referer": "http://localhost:99999/login"},
    )
    assert r1.status_code == 403
    assert r1.json() == {"detail": "CSRF verification failed: untrusted referer"}

    # HTTPS port > 65535
    r2 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Referer": "https://localhost:99999/login"},
    )
    assert r2.status_code == 403
    assert r2.json() == {"detail": "CSRF verification failed: untrusted referer"}

    # Port 0 (reserved / invalid)
    r3 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Referer": "http://localhost:0/login"},
    )
    assert r3.status_code == 403
    assert r3.json() == {"detail": "CSRF verification failed: untrusted referer"}


def test_csrf_bracketed_ipv6_origin_accepted(client: TestClient):
    """Verify that a valid bracketed IPv6 origin passes CSRF verification when explicitly trusted."""
    response = client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "pass"},
        headers={"Origin": "http://[::1]:8000"},
    )
    # Passes CSRF (because http://[::1]:8000 is in cors_origins), fails credentials (401)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_csrf_invalid_ipv6_origin_rejected(client: TestClient):
    """Verify that malformed or unbracketed IPv6 origins are rejected with HTTP 403."""
    # Unclosed bracket
    r1 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://[::1"},
    )
    assert r1.status_code == 403
    assert r1.json() == {"detail": "CSRF verification failed: untrusted origin"}

    # Invalid IPv6 address in brackets
    r2 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://[2001:db8:::1]:8000"},
    )
    assert r2.status_code == 403
    assert r2.json() == {"detail": "CSRF verification failed: untrusted origin"}

    # Missing brackets for IPv6 address
    r3 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://::1:8000"},
    )
    assert r3.status_code == 403
    assert r3.json() == {"detail": "CSRF verification failed: untrusted origin"}


def test_csrf_origin_userinfo_rejected(client: TestClient):
    """Verify that Origin headers containing user-information components are rejected with HTTP 403."""
    r1 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://user@localhost:5173"},
    )
    assert r1.status_code == 403
    assert r1.json() == {"detail": "CSRF verification failed: untrusted origin"}

    r2 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://user:pass@localhost:5173"},
    )
    assert r2.status_code == 403
    assert r2.json() == {"detail": "CSRF verification failed: untrusted origin"}


def test_csrf_origin_with_path_or_query_rejected(client: TestClient):
    """Verify that Origin headers containing paths, queries, or fragments are rejected with HTTP 403."""
    # Origin with subpath
    r1 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://localhost:5173/subpath"},
    )
    assert r1.status_code == 403
    assert r1.json() == {"detail": "CSRF verification failed: untrusted origin"}

    # Origin with query parameters
    r2 = client.post(
        "/auth/login",
        json={"email": "any@example.com", "password": "pass"},
        headers={"Origin": "http://localhost:5173?param=1"},
    )
    assert r2.status_code == 403
    assert r2.json() == {"detail": "CSRF verification failed: untrusted origin"}


# ===========================================================================
# 5. RATE LIMITING TESTS
# ===========================================================================


def test_register_rate_limiting_enforced(client: TestClient):
    """Verify that exceeding registration rate limit returns HTTP 429."""
    # settings.rate_limit_register is "5/minute"
    for i in range(5):
        client.post(
            "/auth/register",
            json={
                "email": f"rate_reg_{i}@example.com",
                "password": "ValidPassword123!",
                "full_name": f"User {i}",
            },
            headers=TRUSTED_HEADERS,
        )

    # 6th request must exceed rate limit
    r_limited = client.post(
        "/auth/register",
        json={
            "email": "rate_reg_blocked@example.com",
            "password": "ValidPassword123!",
            "full_name": "Blocked User",
        },
        headers=TRUSTED_HEADERS,
    )
    assert r_limited.status_code == 429
    assert r_limited.json() == {"detail": "Too many requests. Please try again later."}


def test_login_rate_limiting_enforced(client: TestClient):
    """Verify that exceeding login rate limit returns HTTP 429."""
    # settings.rate_limit_login is "10/minute"
    for i in range(10):
        client.post(
            "/auth/login",
            json={"email": "attempt@example.com", "password": "wrong"},
            headers=TRUSTED_HEADERS,
        )

    # 11th attempt must be rate-limited
    r_limited = client.post(
        "/auth/login",
        json={"email": "attempt@example.com", "password": "wrong"},
        headers=TRUSTED_HEADERS,
    )
    assert r_limited.status_code == 429
    assert r_limited.json() == {"detail": "Too many requests. Please try again later."}
