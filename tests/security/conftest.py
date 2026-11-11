"""
Shared fixtures and test utilities for LedgerLine security test suite.

Provides:
- In-memory SQLite test database with PRAGMA foreign_keys=ON.
- TestClient configured with get_db override and rate-limiter resets.
- Helper factories for users, accounts, and session logins.
- Standard trusted origin headers for CSRF protection.
"""

from collections.abc import Generator
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.deps import get_db
from backend.app.config import settings
from backend.app.core.rate_limit import limiter
from backend.app.main import app
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.base import Base
from backend.app.models.user import User, UserRole
from backend.app.services.account_service import get_or_create_system_clearing_account
from backend.app.services.auth_service import create_session, register_user

TRUSTED_ORIGIN = "http://localhost:5173"
TRUSTED_HEADERS = {"Origin": TRUSTED_ORIGIN}


@pytest.fixture
def db_engine():
    """Create an isolated, schema-initialized in-memory SQLite database engine."""
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
    """Provide an isolated database session for test state setup and inspection."""
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine) -> Generator[TestClient, None, None]:
    """Provide a FastAPI TestClient with database session override."""
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


def make_user(
    db: Session,
    email: str = "user@example.com",
    password: str = "SecurePass123!",
    full_name: str = "Test User",
    role: UserRole = UserRole.HOLDER,
    is_active: bool = True,
) -> User:
    """Create a verified test user in the database."""
    user = register_user(
        db=db,
        email=email,
        password=password,
        full_name=full_name,
    )
    if role != UserRole.HOLDER:
        user.role = role
    if not is_active:
        user.is_active = False
    db.commit()
    db.refresh(user)
    return user


def make_account(
    db: Session,
    user: User,
    account_name: str = "Operating Account",
    currency: str = "INR",
    balance_paise: int = 100000,
    status: AccountStatus = AccountStatus.ACTIVE,
    membership_role: MembershipRole = MembershipRole.OWNER,
) -> tuple[Account, AccountMembership]:
    """Create an account and assign membership to user."""
    # Ensure system clearing account exists
    get_or_create_system_clearing_account(db)

    account = Account(
        account_number=f"ACC-{uuid.uuid4().hex[:8].upper()}",
        account_name=account_name,
        currency=currency,
        balance=balance_paise,
        status=status,
    )
    db.add(account)
    db.flush()

    membership = AccountMembership(
        user_id=user.id,
        account_id=account.id,
        membership_role=membership_role,
    )
    db.add(membership)
    db.commit()
    db.refresh(account)
    db.refresh(membership)
    return account, membership


def login_client(client: TestClient, db: Session, user: User) -> str:
    """Issue a valid session for user and attach session cookie to client."""
    sess_res = create_session(db, user)
    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
    return sess_res.raw_token
