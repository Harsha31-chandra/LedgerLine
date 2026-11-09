"""
Integration and API tests for LedgerLine administrative endpoints (/admin/accounts).

Covers:
- GET /admin/accounts: Successful administrative listing for authenticated ADMIN.
- Returns all non-system customer accounts across all holders.
- Excludes SYSTEM_CLEARING account from administrative registry response.
- Rejection of non-admin roles: HOLDER and AUDITOR return 403 Forbidden.
- Rejection of unauthenticated callers: returns 401 Unauthorized.
- Principle of Least Privilege / Separation of Duties: Admin visibility in /admin/accounts
  does NOT grant operational access (e.g. deposit, withdraw, transfer) on customer accounts.
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
from backend.app.core.security import hash_password
from backend.app.main import app
from backend.app.models.base import Base
from backend.app.models.user import User, UserRole
from backend.app.services.account_service import (
    SYSTEM_CLEARING_ACCOUNT_NUMBER,
    create_account,
    get_or_create_system_clearing_account,
)
from backend.app.services.auth_service import create_session

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


def _create_user(
    db: Session,
    email: str,
    role: UserRole = UserRole.HOLDER,
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password("ValidPass123!"),
        full_name=f"User {email}",
        role=role.value,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_admin_accounts_requires_authentication(client: TestClient):
    """GET /admin/accounts without a session cookie returns 401 Unauthorized."""
    response = client.get("/admin/accounts", headers=TRUSTED_HEADERS)
    assert response.status_code == 401


def test_admin_accounts_forbidden_for_holder(client: TestClient, db_session: Session):
    """GET /admin/accounts by HOLDER role returns 403 Forbidden."""
    holder = _create_user(db_session, "holder_admin_test@example.com", role=UserRole.HOLDER)
    _login(client, db_session, holder)

    response = client.get("/admin/accounts", headers=TRUSTED_HEADERS)
    assert response.status_code == 403
    assert response.json().get("detail") == "Insufficient role permissions"


def test_admin_accounts_forbidden_for_auditor(client: TestClient, db_session: Session):
    """GET /admin/accounts by AUDITOR role returns 403 Forbidden."""
    auditor = _create_user(db_session, "auditor_admin_test@example.com", role=UserRole.AUDITOR)
    _login(client, db_session, auditor)

    response = client.get("/admin/accounts", headers=TRUSTED_HEADERS)
    assert response.status_code == 403
    assert response.json().get("detail") == "Insufficient role permissions"


def test_admin_accounts_returns_all_customer_accounts_excluding_clearing(
    client: TestClient, db_session: Session
):
    """GET /admin/accounts by ADMIN returns all customer accounts, excluding SYSTEM_CLEARING."""
    admin = _create_user(db_session, "admin_registry@example.com", role=UserRole.ADMIN)
    cust1 = _create_user(db_session, "cust1@example.com", role=UserRole.HOLDER)
    cust2 = _create_user(db_session, "cust2@example.com", role=UserRole.HOLDER)

    # Initialize SYSTEM_CLEARING
    clearing = get_or_create_system_clearing_account(db_session)
    assert clearing.account_number == SYSTEM_CLEARING_ACCOUNT_NUMBER

    # Create accounts for cust1 and cust2
    acc1, _ = create_account(db_session, admin, "Cust 1 Checking", owner_user_id=cust1.id)
    acc2, _ = create_account(db_session, admin, "Cust 2 Savings", owner_user_id=cust2.id)

    _login(client, db_session, admin)
    response = client.get("/admin/accounts", headers=TRUSTED_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2

    account_numbers = [item["account_number"] for item in data]
    assert SYSTEM_CLEARING_ACCOUNT_NUMBER not in account_numbers
    assert acc1.account_number in account_numbers
    assert acc2.account_number in account_numbers

    # Verify AccountResponse schema fields
    for item in data:
        assert "id" in item
        assert "account_number" in item
        assert "account_name" in item
        assert "balance" in item
        assert "currency" in item
        assert "status" in item
        assert "created_at" in item


def test_admin_cannot_operate_on_customer_account_without_membership(
    client: TestClient, db_session: Session
):
    """Admin visibility in /admin/accounts does NOT grant operational execution rights.

    Demonstrates:
    1. Unlinked Admin cannot deposit or withdraw (rejected with 404 anti-IDOR protection).
    2. Admin with only VIEWER membership cannot deposit or withdraw (rejected with 403 Forbidden).
    """
    admin = _create_user(db_session, "admin_no_op@example.com", role=UserRole.ADMIN)
    customer = _create_user(db_session, "cust_target@example.com", role=UserRole.HOLDER)

    # Admin provisions account for customer
    cust_acc, _ = create_account(db_session, admin, "Customer Vault", owner_user_id=customer.id)

    _login(client, db_session, admin)

    # 1. Admin can see account in registry
    list_res = client.get("/admin/accounts", headers=TRUSTED_HEADERS)
    assert list_res.status_code == 200
    assert any(a["id"] == str(cust_acc.id) for a in list_res.json())

    # 2. Admin cannot execute deposit on customer account without membership (anti-IDOR 404)
    dep_payload = {
        "account_id": str(cust_acc.id),
        "amount_paise": 50000,
        "description": "Unauthorized Admin Deposit",
    }
    dep_headers = {
        **TRUSTED_HEADERS,
        "X-Idempotency-Key": str(uuid.uuid4()),
    }
    dep_res = client.post("/transactions/deposit", json=dep_payload, headers=dep_headers)
    assert dep_res.status_code == 404

    # 3. Admin cannot execute withdrawal on customer account without membership (anti-IDOR 404)
    wth_payload = {
        "account_id": str(cust_acc.id),
        "amount_paise": 10000,
        "description": "Unauthorized Admin Withdrawal",
    }
    wth_headers = {
        **TRUSTED_HEADERS,
        "X-Idempotency-Key": str(uuid.uuid4()),
    }
    wth_res = client.post("/transactions/withdraw", json=wth_payload, headers=wth_headers)
    assert wth_res.status_code == 404

    # 4. If admin is added as a VIEWER, attempting deposit is rejected with 403 Forbidden
    from backend.app.models.account_membership import AccountMembership, MembershipRole
    viewer_membership = AccountMembership(
        user_id=admin.id,
        account_id=cust_acc.id,
        membership_role=MembershipRole.VIEWER.value,
    )
    db_session.add(viewer_membership)
    db_session.commit()

    dep_viewer_res = client.post("/transactions/deposit", json=dep_payload, headers=dep_headers)
    assert dep_viewer_res.status_code == 403
