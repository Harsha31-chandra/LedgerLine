"""
Tests for Admin and Auditor API endpoints:
- GET /admin/stats
- GET /admin/users
- POST /admin/memberships
- GET /admin/audit-logs
- GET /audit/overview
- GET /audit/accounts
- GET /audit/transactions
- GET /audit/logs
"""

from typing import Generator
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
from backend.app.services.account_service import SYSTEM_CLEARING_ACCOUNT_NUMBER
from backend.app.services.auth_service import create_session, register_user

TRUSTED_ORIGIN = "http://localhost:5173"
TRUSTED_HEADERS = {"Origin": TRUSTED_ORIGIN}


@pytest.fixture
def db_engine():
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
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine) -> Generator[TestClient, None, None]:
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
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_user(
    db: Session,
    username: str,
    email: str,
    role: UserRole = UserRole.HOLDER,
) -> User:
    user = register_user(
        db,
        email=email,
        password="ValidPassword123!",
        full_name=username,
    )
    user.role = role.value
    db.commit()
    db.refresh(user)
    return user


def login(client: TestClient, db: Session, user: User) -> str:
    session, raw_token = create_session(db, user)
    client.cookies.set(settings.session_cookie_name, raw_token)
    return raw_token


def test_admin_stats_and_users_access_control(client: TestClient, db_session: Session):
    admin = make_user(db_session, "admin_user", "admin@ledger.com", UserRole.ADMIN)
    auditor = make_user(db_session, "auditor_user", "auditor@ledger.com", UserRole.AUDITOR)
    holder = make_user(db_session, "holder_user", "holder@ledger.com", UserRole.HOLDER)

    # 1. Unauthenticated -> 401
    client.cookies.clear()
    assert client.get("/admin/stats", headers=TRUSTED_HEADERS).status_code == 401
    assert client.get("/admin/users", headers=TRUSTED_HEADERS).status_code == 401

    # 2. Holder -> 403
    login(client, db_session, holder)
    assert client.get("/admin/stats", headers=TRUSTED_HEADERS).status_code == 403
    assert client.get("/admin/users", headers=TRUSTED_HEADERS).status_code == 403

    # 3. Auditor -> 403
    login(client, db_session, auditor)
    assert client.get("/admin/stats", headers=TRUSTED_HEADERS).status_code == 403
    assert client.get("/admin/users", headers=TRUSTED_HEADERS).status_code == 403

    # 4. Admin -> 200
    login(client, db_session, admin)
    resp = client.get("/admin/stats", headers=TRUSTED_HEADERS)
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total_users"] == 3
    assert stats["total_accounts"] == 0

    resp_users = client.get("/admin/users", headers=TRUSTED_HEADERS)
    assert resp_users.status_code == 200
    users = resp_users.json()
    assert len(users) == 3


def test_admin_memberships_assignment(client: TestClient, db_session: Session):
    admin = make_user(db_session, "admin_mbr", "admin_mbr@ledger.com", UserRole.ADMIN)
    holder = make_user(db_session, "holder_mbr", "holder_mbr@ledger.com", UserRole.HOLDER)

    # Create account
    account = Account(
        account_name="Corporate Account",
        account_number="ACC-CORP-001",
        currency="INR",
        balance=500000,
        status=AccountStatus.ACTIVE,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    # Holder cannot assign membership -> 403
    login(client, db_session, holder)
    resp = client.post(
        "/admin/memberships",
        headers=TRUSTED_HEADERS,
        json={
            "account_id": str(account.id),
            "user_id": str(holder.id),
            "role": "OPERATOR",
        },
    )
    assert resp.status_code == 403

    # Admin can assign membership -> 200
    login(client, db_session, admin)
    resp = client.post(
        "/admin/memberships",
        headers=TRUSTED_HEADERS,
        json={
            "account_id": str(account.id),
            "user_id": str(holder.id),
            "role": "OPERATOR",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["membership_role"] == "OPERATOR"

    # Verify membership recorded in DB
    membership = (
        db_session.query(AccountMembership)
        .filter_by(account_id=account.id, user_id=holder.id)
        .first()
    )
    assert membership is not None
    assert membership.membership_role == "OPERATOR"


def test_audit_endpoints_access_control(client: TestClient, db_session: Session):
    admin = make_user(db_session, "admin_audit", "admin_audit@ledger.com", UserRole.ADMIN)
    auditor = make_user(db_session, "auditor_audit", "auditor_audit@ledger.com", UserRole.AUDITOR)
    holder = make_user(db_session, "holder_audit", "holder_audit@ledger.com", UserRole.HOLDER)

    # Unauthenticated -> 401
    client.cookies.clear()
    assert client.get("/audit/overview", headers=TRUSTED_HEADERS).status_code == 401
    assert client.get("/audit/accounts", headers=TRUSTED_HEADERS).status_code == 401
    assert client.get("/audit/transactions", headers=TRUSTED_HEADERS).status_code == 401
    assert client.get("/audit/logs", headers=TRUSTED_HEADERS).status_code == 401

    # Holder -> 403
    login(client, db_session, holder)
    assert client.get("/audit/overview", headers=TRUSTED_HEADERS).status_code == 403
    assert client.get("/audit/accounts", headers=TRUSTED_HEADERS).status_code == 403
    assert client.get("/audit/transactions", headers=TRUSTED_HEADERS).status_code == 403
    assert client.get("/audit/logs", headers=TRUSTED_HEADERS).status_code == 403

    # Auditor -> 200
    login(client, db_session, auditor)
    resp_overview = client.get("/audit/overview", headers=TRUSTED_HEADERS)
    assert resp_overview.status_code == 200
    assert "total_accounts" in resp_overview.json()

    resp_accounts = client.get("/audit/accounts", headers=TRUSTED_HEADERS)
    assert resp_accounts.status_code == 200

    resp_txns = client.get("/audit/transactions", headers=TRUSTED_HEADERS)
    assert resp_txns.status_code == 200

    resp_logs = client.get("/audit/logs", headers=TRUSTED_HEADERS)
    assert resp_logs.status_code == 200

    # Admin -> also 200 for audit routes
    login(client, db_session, admin)
    assert client.get("/audit/overview", headers=TRUSTED_HEADERS).status_code == 200
    assert client.get("/admin/audit-logs", headers=TRUSTED_HEADERS).status_code == 200
