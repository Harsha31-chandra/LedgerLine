"""
End-to-end integration and API tests for LedgerLine account endpoints.

Covers:
- POST /accounts: Admin account creation and atomic initial ownership.
- Rejection of account creation by non-admin users and unauthenticated callers.
- GET /accounts: Isolation of accounts belonging exclusively to authenticated user.
- GET /accounts/{account_id}: Anti-IDOR (404 for unowned accounts).
- PATCH /accounts/{account_id}: Metadata update permissions (OWNER vs non-owners).
- POST /accounts/{account_id}/status: Administrative freeze/close capabilities.
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


def _login(client: TestClient, db: Session, user: User) -> None:
    sess_res = create_session(db, user)
    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)


# ===========================================================================
# 1. POST /accounts (CREATE ACCOUNT)
# ===========================================================================


def test_api_create_account_by_admin_success(client: TestClient, db_session: Session):
    """Verify admin can create an account and receive 201 Created."""
    admin = register_user(db_session, "admin_api@example.com", "Password123!", "Admin API")
    admin.role = UserRole.ADMIN.value
    customer = register_user(db_session, "cust_api@example.com", "Password123!", "Cust API")
    db_session.commit()

    _login(client, db_session, admin)

    payload = {
        "account_name": "API Customer Wallet",
        "currency": "INR",
        "owner_user_id": str(customer.id),
    }
    response = client.post("/accounts", json=payload, headers=TRUSTED_HEADERS)

    assert response.status_code == 201
    data = response.json()
    assert data["account_name"] == "API Customer Wallet"
    assert data["currency"] == "INR"
    assert data["balance"] == 0
    assert data["status"] == "ACTIVE"
    assert data["membership_role"] == "OWNER"
    assert "account_number" in data


def test_api_create_account_by_holder_rejected(client: TestClient, db_session: Session):
    """Verify HOLDER cannot create accounts (HTTP 403)."""
    holder = register_user(db_session, "holder_api@example.com", "Password123!", "Holder API")
    _login(client, db_session, holder)

    payload = {"account_name": "Unauthorized Wallet"}
    response = client.post("/accounts", json=payload, headers=TRUSTED_HEADERS)

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient role permissions"}


def test_api_create_account_unauthenticated_rejected(client: TestClient):
    """Verify unauthenticated request returns HTTP 401."""
    response = client.post("/accounts", json={"account_name": "No Auth"}, headers=TRUSTED_HEADERS)
    assert response.status_code == 401


# ===========================================================================
# 2. GET /accounts (LIST ACCOUNTS)
# ===========================================================================


def test_api_list_accounts_returns_only_user_memberships(client: TestClient, db_session: Session):
    """Verify GET /accounts returns only accounts belonging to the authenticated user."""
    admin = register_user(db_session, "admin_list@example.com", "Password123!", "Admin List")
    admin.role = UserRole.ADMIN.value
    user1 = register_user(db_session, "u1@example.com", "Password123!", "User 1")
    user2 = register_user(db_session, "u2@example.com", "Password123!", "User 2")
    db_session.commit()

    # Create account for user1
    acc1 = Account(account_number="LL-U1-01", account_name="U1 Wallet", balance=1000)
    db_session.add(acc1)
    db_session.commit()
    db_session.add(AccountMembership(user_id=user1.id, account_id=acc1.id, membership_role="OWNER"))

    # Create account for user2
    acc2 = Account(account_number="LL-U2-01", account_name="U2 Wallet", balance=2000)
    db_session.add(acc2)
    db_session.commit()
    db_session.add(AccountMembership(user_id=user2.id, account_id=acc2.id, membership_role="OWNER"))
    db_session.commit()

    # User 1 logs in
    _login(client, db_session, user1)
    res1 = client.get("/accounts")
    assert res1.status_code == 200
    items1 = res1.json()
    assert len(items1) == 1
    assert items1[0]["account_number"] == "LL-U1-01"

    # User 2 logs in
    _login(client, db_session, user2)
    res2 = client.get("/accounts")
    assert res2.status_code == 200
    items2 = res2.json()
    assert len(items2) == 1
    assert items2[0]["account_number"] == "LL-U2-01"


# ===========================================================================
# 3. GET /accounts/{id} (RETRIEVE ACCOUNT & IDOR DEFENSE)
# ===========================================================================


def test_api_get_account_anti_idor(client: TestClient, db_session: Session):
    """Verify accessing an account where user lacks membership returns HTTP 404."""
    user1 = register_user(db_session, "legit@example.com", "Password123!", "Legit")
    user2 = register_user(db_session, "snooper@example.com", "Password123!", "Snooper")

    acc = Account(account_number="LL-SECRET-01", account_name="Secret Vault", balance=50000)
    db_session.add(acc)
    db_session.commit()
    db_session.add(AccountMembership(user_id=user1.id, account_id=acc.id, membership_role="OWNER"))
    db_session.commit()

    _login(client, db_session, user2)
    response = client.get(f"/accounts/{acc.id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Account not found"}


# ===========================================================================
# 4. PATCH /accounts/{id} (UPDATE DETAILS)
# ===========================================================================


def test_api_patch_account_by_owner_success(client: TestClient, db_session: Session):
    """Verify OWNER can update account metadata."""
    user = register_user(db_session, "owner_patch@example.com", "Password123!", "Owner Patch")
    acc = Account(account_number="LL-PATCH-01", account_name="Old Label", balance=0)
    db_session.add(acc)
    db_session.commit()
    db_session.add(AccountMembership(user_id=user.id, account_id=acc.id, membership_role="OWNER"))
    db_session.commit()

    _login(client, db_session, user)

    response = client.patch(
        f"/accounts/{acc.id}",
        json={"account_name": "Updated Label"},
        headers=TRUSTED_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["account_name"] == "Updated Label"


# ===========================================================================
# 5. POST /accounts/{id}/status (ADMIN STATUS CHANGE)
# ===========================================================================


def test_api_post_status_by_admin(client: TestClient, db_session: Session):
    """Verify Admin can freeze an account."""
    admin = register_user(db_session, "admin_freeze@example.com", "Password123!", "Admin Freeze")
    admin.role = UserRole.ADMIN.value
    acc = Account(account_number="LL-FRZ-01", account_name="To Freeze", balance=0)
    db_session.add(acc)
    db_session.commit()

    _login(client, db_session, admin)

    response = client.post(
        f"/accounts/{acc.id}/status",
        json={"status": "FROZEN"},
        headers=TRUSTED_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "FROZEN"


def test_api_post_status_clearing_account_forbidden(client: TestClient, db_session: Session):
    """Verify Admin cannot freeze or close the system clearing account (SEC-002, returns HTTP 403)."""
    admin = register_user(db_session, "admin_clearing@example.com", "Password123!", "Admin Clearing")
    admin.role = UserRole.ADMIN.value
    clearing = Account(
        account_number="SYSTEM_CLEARING",
        account_name="System Clearing",
        balance=0,
        status=AccountStatus.ACTIVE.value,
    )
    db_session.add(clearing)
    db_session.commit()

    _login(client, db_session, admin)

    response = client.post(
        f"/accounts/{clearing.id}/status",
        json={"status": "FROZEN"},
        headers=TRUSTED_HEADERS,
    )
    assert response.status_code == 403
    assert "system clearing account status cannot be modified" in response.json()["detail"].lower()
