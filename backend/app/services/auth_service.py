"""
Authentication and session lifecycle service for LedgerLine.

Provides:
- User registration with normalized email and Argon2id password hashing.
- Server-side role assignment (defaulting strictly to UserRole.HOLDER).
- Timing-attack-resistant credential authentication with dummy Argon2id verification.
- Secure, opaque session token generation (256-bit CSPRNG via secrets module).
- Hash-only session storage (SHA-256 digests; raw tokens never persisted or logged).
- Session validation (checking expiration, revocation, and user active status).
- Safe session revocation (soft revocation preserving audit trail).

TRANSACTION & SAFETY CONVENTIONS:
- All database operations accept an active SQLAlchemy Session.
- Service methods commit state explicitly on success or rollback on error.
- Timezone-aware UTC timestamps (datetime.now(timezone.utc)) are used exclusively.
- Expiration uses a fixed TTL (defaulting to settings.session_ttl_minutes = 1440 min).
"""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Final, NamedTuple
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from backend.app.config import settings
from backend.app.core.exceptions import (
    AuthenticationError,
    InactiveUserError,
    SessionExpiredError,
    SessionNotFoundError,
    SessionRevokedError,
    UserAlreadyExistsError,
)
from backend.app.core.security import hash_password, verify_password
from backend.app.models.session import Session as SessionModel
from backend.app.models.user import User, UserRole

# Pre-computed dummy Argon2id hash using RFC 9106 parameters (m=65536, t=3, p=4, 16-byte salt, 32-byte key)
# Executed when an email does not exist to mitigate timing side channels between nonexistent accounts
# and existing accounts. Note: This defense substantially reduces coarse timing discrepancies, but does
# not guarantee mathematically constant-time authentication across network, GC, or database layers.
DUMMY_ARGON2_HASH: Final[str] = (
    "$argon2id$v=19$m=65536,t=3,p=4$ri3VeIsCbcnp1L4vXCoIyQ$EeVDbO8knjJihCIErWKfgyYFrTIX7EY9qTS+lVQYlfU"
)

__all__ = [
    "DUMMY_ARGON2_HASH",
    "SessionCreateResult",
    "authenticate_user",
    "create_session",
    "hash_session_token",
    "normalize_email",
    "register_user",
    "revoke_all_user_sessions",
    "revoke_session",
    "validate_session",
]


class SessionCreateResult(NamedTuple):
    """Container holding the persisted Session database entity and the one-time raw token."""

    session: SessionModel
    raw_token: str


def normalize_email(email: str) -> str:
    """Normalize email address by stripping whitespace and converting to lowercase.

    Args:
        email: Raw email string.

    Returns:
        Stripped, lowercased email string.

    Raises:
        ValueError: If email is empty or not a string.
    """
    if not isinstance(email, str) or not email.strip():
        raise ValueError("Email must be a non-empty string")
    return email.strip().lower()


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime object is timezone-aware in UTC (normalizing naive SQLite timestamps)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hash_session_token(token: str) -> str:
    """Compute standard SHA-256 hex digest of a raw session token.

    Args:
        token: Raw unhashed session token.

    Returns:
        64-character lowercase hex digest suitable for Session.token_hash.
    """
    if not isinstance(token, str) or not token:
        raise ValueError("Session token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_user_email_unique_violation(exc: IntegrityError) -> bool:
    """Determine whether an IntegrityError was caused by the User email unique constraint.

    Inspects driver-specific diagnostic attributes across supported database engines:
    - PostgreSQL (psycopg2 / psycopg3 / asyncpg):
      Checks for SQLSTATE '23505' (unique_violation) and verifies that the constraint
      is 'ix_users_email' (or standard naming variants) or references users.email.
    - SQLite (sqlite3):
      Checks for SQLITE_CONSTRAINT_UNIQUE error codes/names and verifies the target
      is specifically 'users.email' or 'ix_users_email'.
    - Fallback:
      Matches strict driver error representations for the specific email uniqueness
      constraint while rejecting unrelated unique constraints, check constraints,
      or foreign key violations.
    """
    orig = getattr(exc, "orig", None)

    # 1. PostgreSQL driver inspection (psycopg2, psycopg3, asyncpg)
    pgcode = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    if pgcode is not None:
        if str(pgcode) != "23505":
            # Distinct SQLSTATE (e.g. 23514 check violation, 23503 foreign key violation)
            return False

        # It is a unique_violation (23505) — inspect diagnostics for target constraint
        diag = getattr(orig, "diag", None)
        constraint_name = (
            getattr(diag, "constraint_name", None)
            or getattr(orig, "constraint_name", None)
        )
        if constraint_name:
            if constraint_name in ("ix_users_email", "users_email_key", "uq_users_email"):
                return True
            table_name = getattr(diag, "table_name", None) or getattr(orig, "table_name", None)
            if table_name == "users" and "email" in constraint_name:
                return True
            # Distinct unique constraint (e.g. uq_account_memberships_user_account)
            return False

        # Check detail string from diagnostics if available
        detail = getattr(diag, "message_detail", None) or getattr(orig, "detail", None)
        if detail and ("(email)=" in detail or "Key (email)=" in detail):
            return True

    # 2. SQLite driver inspection (sqlite3)
    sqlite_errorname = getattr(orig, "sqlite_errorname", None)
    sqlite_errorcode = getattr(orig, "sqlite_errorcode", None)
    if sqlite_errorname is not None or sqlite_errorcode is not None:
        is_sqlite_unique = (
            sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE"
            or sqlite_errorcode == 2067  # SQLITE_CONSTRAINT_UNIQUE extended code
        )
        if not is_sqlite_unique:
            # Check constraint, not null constraint, etc.
            return False

        orig_msg = str(orig)
        if "users.email" in orig_msg or "ix_users_email" in orig_msg:
            return True
        return False

    # 3. Direct constraint attribute inspection (common in SQLAlchemy/mock objects)
    constraint_name = getattr(orig, "constraint_name", None)
    if constraint_name in ("ix_users_email", "users_email_key", "uq_users_email"):
        return True

    # 4. Strict string matching on exception representation
    full_msg = f"{orig} {exc}".lower()
    if 'violates unique constraint "ix_users_email"' in full_msg or "violates unique constraint 'ix_users_email'" in full_msg:
        return True
    if 'violates unique constraint "users_email_key"' in full_msg or "violates unique constraint 'users_email_key'" in full_msg:
        return True
    if "unique constraint failed: users.email" in full_msg or "unique constraint failed: index 'ix_users_email'" in full_msg:
        return True

    return False


def register_user(
    db: DbSession,
    email: str,
    password: str,
    full_name: str,
) -> User:
    """Register a new user account with secure Argon2id password hashing.

    Public registration strictly assigns UserRole.HOLDER server-side.
    Client-controlled administrative or auditor roles are forbidden.

    Args:
        db: Active SQLAlchemy database session.
        email: Plaintext email address to register.
        password: Plaintext password (non-empty string up to 128 characters).
        full_name: Full display/legal name of the user.

    Returns:
        Newly created and persisted User entity.

    Raises:
        UserAlreadyExistsError: If a user with the normalized email already exists.
        ValueError: If password or full name is empty.
    """
    normalized = normalize_email(email)
    cleaned_name = full_name.strip() if isinstance(full_name, str) else ""
    if not cleaned_name:
        raise ValueError("Full name cannot be empty")

    # Check email uniqueness against database
    existing = db.scalars(select(User).where(User.email == normalized)).first()
    if existing is not None:
        raise UserAlreadyExistsError(f"User with email '{normalized}' already exists")

    # Hash password using Argon2id (validates non-empty password)
    password_hash = hash_password(password)

    new_user = User(
        email=normalized,
        password_hash=password_hash,
        full_name=cleaned_name,
        role=UserRole.HOLDER,
        is_active=True,
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user
    except IntegrityError as exc:
        db.rollback()
        if _is_user_email_unique_violation(exc):
            raise UserAlreadyExistsError(f"User with email '{normalized}' already exists") from exc
        raise
    except Exception:
        db.rollback()
        raise


def authenticate_user(
    db: DbSession,
    email: str,
    password: str,
) -> User:
    """Authenticate user credentials using Argon2id with timing attack mitigation.

    If the user does not exist, a dummy Argon2id hash verification is executed
    with compatible cryptographic parameters before returning failure, mitigating
    timing side channels that could facilitate account enumeration. (Note: does not
    guarantee constant-time authentication across variable system environments).

    Args:
        db: Active SQLAlchemy database session.
        email: User email address.
        password: Candidate plaintext password.

    Returns:
        Authenticated User entity.

    Raises:
        AuthenticationError: If email does not exist or password does not match.
        InactiveUserError: If user exists and password matches, but account is deactivated.
    """
    try:
        normalized = normalize_email(email)
    except ValueError:
        # Invalid email format triggers dummy verification to maintain uniform timing
        verify_password(password, DUMMY_ARGON2_HASH)
        raise AuthenticationError("Invalid email or password")

    user = db.scalars(select(User).where(User.email == normalized)).first()

    if user is None:
        # Timing protection: execute dummy Argon2id verification for nonexistent users
        verify_password(password, DUMMY_ARGON2_HASH)
        raise AuthenticationError("Invalid email or password")

    # User exists: verify candidate password against stored Argon2id hash
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid email or password")

    # Verify active account status
    if not user.is_active:
        raise InactiveUserError("User account is inactive")

    return user


def create_session(
    db: DbSession,
    user: User,
    ttl_minutes: int | None = None,
) -> SessionCreateResult:
    """Create a new server-side session for an authenticated user.

    Generates a cryptographically random 256-bit opaque token via secrets.token_urlsafe(32).
    Computes and stores only the SHA-256 digest in Session.token_hash. The raw token
    is returned to the caller exactly once and is never stored in the database.

    Args:
        db: Active SQLAlchemy database session.
        user: Authenticated User entity.
        ttl_minutes: Optional explicit TTL in minutes (must be a positive integer > 0;
            defaults to settings.session_ttl_minutes).

    Returns:
        SessionCreateResult containing the persisted Session entity and the one-time raw token.

    Raises:
        InactiveUserError: If the user account is inactive.
        ValueError: If ttl_minutes is not a strictly positive integer.
    """
    if not user.is_active:
        raise InactiveUserError("Cannot create a session for an inactive user")

    # Generate 32 bytes (256 bits) of CSPRNG randomness, encoded as 43 URL-safe characters
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(raw_token)

    now = datetime.now(timezone.utc)
    ttl = ttl_minutes if ttl_minutes is not None else settings.session_ttl_minutes
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
        raise ValueError("Session TTL must be a positive integer greater than zero")
    expires_at = now + timedelta(minutes=ttl)

    new_session = SessionModel(
        user_id=user.id,
        token_hash=token_hash,
        created_at=now,
        last_activity_at=now,
        expires_at=expires_at,
        revoked_at=None,
    )

    try:
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return SessionCreateResult(session=new_session, raw_token=raw_token)
    except Exception:
        db.rollback()
        raise


def validate_session(
    db: DbSession,
    raw_token: str,
) -> tuple[SessionModel, User]:
    """Validate a raw session token against the database.

    Hashes the token with SHA-256 before querying. Validates that:
    1. The session exists.
    2. The session has not been explicitly revoked (revoked_at is None).
    3. The session has not expired (expires_at > current UTC time).
    4. The associated user account is active.

    Per initial design, uses fixed expiration (no sliding window).

    Args:
        db: Active SQLAlchemy database session.
        raw_token: The client's raw session token.

    Returns:
        Tuple of (Session, User) for the validated session.

    Raises:
        SessionNotFoundError: If token does not match any session.
        SessionRevokedError: If the session was revoked.
        SessionExpiredError: If the session has passed its expiration time.
        InactiveUserError: If the associated user account is inactive.
    """
    try:
        token_hash = hash_session_token(raw_token)
    except ValueError:
        raise SessionNotFoundError("Invalid session token format")

    session = db.scalars(select(SessionModel).where(SessionModel.token_hash == token_hash)).first()

    if session is None:
        raise SessionNotFoundError("Session not found")

    if session.revoked_at is not None:
        raise SessionRevokedError("Session has been revoked")

    now = datetime.now(timezone.utc)
    if _ensure_utc(session.expires_at) <= now:
        raise SessionExpiredError("Session has expired")

    user = session.user
    if user is None:
        # Fallback query if relationship is not eagerly loaded
        user = db.scalars(select(User).where(User.id == session.user_id)).first()

    if user is None or not user.is_active:
        raise InactiveUserError("User account is inactive")

    return session, user


def revoke_session(
    db: DbSession,
    raw_token: str,
) -> SessionModel:
    """Revoke an active session token by recording the revocation timestamp.

    Soft revocation preserves historical auditability while ensuring the token
    cannot be validated or reactivated. Repeated revocations are idempotent and safe.

    Args:
        db: Active SQLAlchemy database session.
        raw_token: The raw session token to revoke.

    Returns:
        The updated Session entity.

    Raises:
        SessionNotFoundError: If the token does not match any existing session.
    """
    try:
        token_hash = hash_session_token(raw_token)
    except ValueError:
        raise SessionNotFoundError("Invalid session token format")

    session = db.scalars(select(SessionModel).where(SessionModel.token_hash == token_hash)).first()

    if session is None:
        raise SessionNotFoundError("Session not found")

    # Idempotent revocation: if not already revoked, record revocation time
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        try:
            db.commit()
            db.refresh(session)
        except Exception:
            db.rollback()
            raise

    return session


def revoke_all_user_sessions(
    db: DbSession,
    user_id: uuid.UUID,
) -> int:
    """Revoke all active sessions for a specified user (e.g. upon password change or deactivation).

    Args:
        db: Active SQLAlchemy database session.
        user_id: UUID of the user whose sessions should be revoked.

    Returns:
        Number of sessions revoked.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        update(SessionModel)
        .where(SessionModel.user_id == user_id)
        .where(SessionModel.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    try:
        result = db.execute(stmt)
        db.commit()
        return result.rowcount
    except Exception:
        db.rollback()
        raise
