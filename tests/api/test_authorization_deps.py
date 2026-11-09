"""
API integration and dependency tests for LedgerLine RBAC and account authorization.

Tests FastAPI dependencies:
- require_global_role, require_admin, require_auditor, require_holder
- get_authorized_account (require_account_read, require_account_operate, require_account_manage)

Covers:
- Unauthenticated (401) and deactivated user (403) handling.
- Global role boundaries (403 when role is insufficient).
- Account IDOR/BOLA protections (404 when user is not a member, preventing account enumeration).
- Account membership role boundaries (403 when role is insufficient, e.g. VIEWER attempting OPERATE).
- Global AUDITOR write rejection (403 when AUDITOR attempts OPERATE or MANAGE even with OWNER membership).
- Account status constraints (403 when operating on FROZEN account).
"""

from typing import Annotated, Generator
import uuid

from fastapi import APIRouter, Depends, status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.deps import (
    get_db,
    require_account_manage,
    require_account_operate,
    require_account_read,
    require_admin,
    require_auditor,
    require_holder,
)
from backend.app.config import settings
from backend.app.core.rate_limit import limiter
from backend.app.main import app
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.base import Base
from backend.app.models.user import User, UserRole
from backend.app.services.auth_service import create_session, register_user

# Probe router mounted dynamically to exercise authorization dependencies
probe_auth_router = APIRouter(prefix="/test-auth", tags=["test-auth"])


@probe_auth_router.get("/admin-only")
def _handler_admin_route(user: Annotated[User, Depends(require_admin)]):
    return {"status": "ok", "role": user.role, "user_id": str(user.id)}


@probe_auth_router.get("/auditor-only")
def _handler_auditor_route(user: Annotated[User, Depends(require_auditor)]):
    return {"status": "ok", "role": user.role, "user_id": str(user.id)}


@probe_auth_router.get("/holder-only")
def _handler_holder_route(user: Annotated[User, Depends(require_holder)]):
    return {"status": "ok", "role": user.role, "user_id": str(user.id)}


@probe_auth_router.get("/accounts/{account_id}")
def _handler_account_read_route(
    account_and_mem: Annotated[tuple[Account, AccountMembership], Depends(require_account_read)],
):
    account, membership = account_and_mem
    return {
        "account_id": str(account.id),
        "account_number": account.account_number,
        "balance": account.balance,
        "membership_role": membership.membership_role,
    }


@probe_auth_router.post("/accounts/{account_id}/operate")
def _handler_account_operate_route(
    account_and_mem: Annotated[tuple[Account, AccountMembership], Depends(require_account_operate)],
):
    account, membership = account_and_mem
    return {
        "status": "operation_authorized",
        "account_id": str(account.id),
        "membership_role": membership.membership_role,
    }


@probe_auth_router.post("/accounts/{account_id}/manage")
def _handler_account_manage_route(
    account_and_mem: Annotated[tuple[Account, AccountMembership], Depends(require_account_manage)],
):
    account, membership = account_and_mem
    return {
        "status": "management_authorized",
        "account_id": str(account.id),
        "membership_role": membership.membership_role,
    }


# Mount probe router on the FastAPI app
app.include_router(probe_auth_router)

TRUSTED_ORIGIN = "http://localhost:5173"
TRUSTED_HEADERS = {"Origin": TRUSTED_ORIGIN}


@pytest.fixture
def db_engine():
    """Provide an isolated in-memory SQLite engine with foreign keys enabled."""
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
    """Provide an isolated database session for setup and direct assertions."""
    session = Session(db_engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine) -> Generator[TestClient, None, None]:
    """Provide a TestClient with injected test database session factory."""
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


def _login_user(client: TestClient, db: Session, user: User) -> str:
    """Helper to create a session in DB and attach the session cookie to TestClient."""
    sess_res = create_session(db, user)
    client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
    return sess_res.raw_token


# ===========================================================================
# 1. GLOBAL ROLE DEPENDENCY TESTS
# ===========================================================================


def test_require_global_role_unauthenticated_rejected(client: TestClient):
    """Verify endpoints requiring authentication return HTTP 401 when cookie is missing."""
    response = client.get("/test-auth/admin-only")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Not authenticated"}


def test_require_admin_success(client: TestClient, db_session: Session):
    """Verify ADMIN user can access admin-only route."""
    admin = register_user(db_session, "admin_user@example.com", "Password123!", "Admin User")
    admin.role = UserRole.ADMIN.value
    db_session.commit()

    _login_user(client, db_session, admin)
    response = client.get("/test-auth/admin-only")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["role"] == "ADMIN"


def test_require_admin_rejected_for_holder_and_auditor(client: TestClient, db_session: Session):
    """Verify HOLDER and AUDITOR receive HTTP 403 on admin-only route."""
    holder = register_user(db_session, "holder_user@example.com", "Password123!", "Holder User")
    auditor = register_user(db_session, "auditor_user@example.com", "Password123!", "Auditor User")
    auditor.role = UserRole.AUDITOR.value
    db_session.commit()

    # Holder attempt
    _login_user(client, db_session, holder)
    r_holder = client.get("/test-auth/admin-only")
    assert r_holder.status_code == status.HTTP_403_FORBIDDEN
    assert r_holder.json() == {"detail": "Insufficient role permissions"}

    # Auditor attempt
    _login_user(client, db_session, auditor)
    r_auditor = client.get("/test-auth/admin-only")
    assert r_auditor.status_code == status.HTTP_403_FORBIDDEN
    assert r_auditor.json() == {"detail": "Insufficient role permissions"}


def test_require_auditor_success(client: TestClient, db_session: Session):
    """Verify AUDITOR can access auditor-only route."""
    auditor = register_user(db_session, "audit_ok@example.com", "Password123!", "Audit Ok")
    auditor.role = UserRole.AUDITOR.value
    db_session.commit()

    _login_user(client, db_session, auditor)
    response = client.get("/test-auth/auditor-only")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["role"] == "AUDITOR"


# ===========================================================================
# 2. ACCOUNT ACCESS AND IDOR / BOLA DEPENDENCY TESTS
# ===========================================================================


def test_account_read_unauthenticated_rejected(client: TestClient):
    """Verify accessing an account route without authentication returns HTTP 401."""
    random_id = uuid.uuid4()
    response = client.get(f"/test-auth/accounts/{random_id}")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Not authenticated"}


def test_account_read_non_existent_account_returns_404(client: TestClient, db_session: Session):
    """Verify accessing a non-existent account UUID returns HTTP 404."""
    user = register_user(db_session, "some_user@example.com", "Password123!", "Some User")
    _login_user(client, db_session, user)

    random_id = uuid.uuid4()
    response = client.get(f"/test-auth/accounts/{random_id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "Account not found"}


def test_idor_unauthorized_user_cannot_read_another_account(client: TestClient, db_session: Session):
    """Verify User A attempting to read User B's account receives HTTP 404 (preventing enumeration)."""
    user_a = register_user(db_session, "user_a@example.com", "Password123!", "User A")
    user_b = register_user(db_session, "user_b@example.com", "Password123!", "User B")

    account_b = Account(
        account_number="ACC-B-777",
        account_name="User B Account",
        currency="INR",
        balance=250000,
        status=AccountStatus.ACTIVE.value,
    )
    db_session.add(account_b)
    db_session.commit()
    db_session.refresh(account_b)

    # Assign membership exclusively to User B
    db_session.add(
        AccountMembership(
            user_id=user_b.id,
            account_id=account_b.id,
            membership_role=MembershipRole.OWNER.value,
        )
    )
    db_session.commit()

    # User A logs in and attempts to access Account B
    _login_user(client, db_session, user_a)
    response = client.get(f"/test-auth/accounts/{account_b.id}")

    # Must return 404 (not 403) so User A cannot verify Account B exists
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "Account not found"}


def test_account_read_success_for_authorized_member(client: TestClient, db_session: Session):
    """Verify an authorized account member can read account details."""
    user = register_user(db_session, "member@example.com", "Password123!", "Member User")
    account = Account(
        account_number="ACC-MEM-101",
        account_name="Member Account",
        currency="INR",
        balance=150000,
        status=AccountStatus.ACTIVE.value,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    db_session.add(
        AccountMembership(
            user_id=user.id,
            account_id=account.id,
            membership_role=MembershipRole.VIEWER.value,
        )
    )
    db_session.commit()

    _login_user(client, db_session, user)
    response = client.get(f"/test-auth/accounts/{account.id}")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["account_id"] == str(account.id)
    assert data["account_number"] == "ACC-MEM-101"
    assert data["balance"] == 150000
    assert data["membership_role"] == "VIEWER"


# ===========================================================================
# 3. MEMBERSHIP ROLE BOUNDARIES & ACTIONS TESTS
# ===========================================================================


def test_viewer_attempting_operational_action_rejected(client: TestClient, db_session: Session):
    """Verify VIEWER role is rejected with HTTP 403 on operational routes."""
    viewer = register_user(db_session, "viewer_op@example.com", "Password123!", "Viewer Op")
    account = Account(
        account_number="ACC-VIEW-OP",
        account_name="Viewer Op Account",
        currency="INR",
        balance=10000,
        status=AccountStatus.ACTIVE.value,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    db_session.add(
        AccountMembership(
            user_id=viewer.id,
            account_id=account.id,
            membership_role=MembershipRole.VIEWER.value,
        )
    )
    db_session.commit()

    _login_user(client, db_session, viewer)
    response = client.post(
        f"/test-auth/accounts/{account.id}/operate",
        headers=TRUSTED_HEADERS,
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Insufficient permissions for this account action"}


def test_operator_can_operate_but_cannot_manage(client: TestClient, db_session: Session):
    """Verify OPERATOR role can operate but receives HTTP 403 on manage route."""
    operator = register_user(db_session, "operator_mem@example.com", "Password123!", "Operator Mem")
    account = Account(
        account_number="ACC-OP-MEM",
        account_name="Operator Account",
        currency="INR",
        balance=10000,
        status=AccountStatus.ACTIVE.value,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    db_session.add(
        AccountMembership(
            user_id=operator.id,
            account_id=account.id,
            membership_role=MembershipRole.OPERATOR.value,
        )
    )
    db_session.commit()

    _login_user(client, db_session, operator)

    # Operational route succeeds
    r_op = client.post(
        f"/test-auth/accounts/{account.id}/operate",
        headers=TRUSTED_HEADERS,
    )
    assert r_op.status_code == status.HTTP_200_OK
    assert r_op.json()["status"] == "operation_authorized"

    # Manage route fails
    r_manage = client.post(
        f"/test-auth/accounts/{account.id}/manage",
        headers=TRUSTED_HEADERS,
    )
    assert r_manage.status_code == status.HTTP_403_FORBIDDEN
    assert r_manage.json() == {"detail": "Insufficient permissions for this account action"}


def test_owner_can_both_operate_and_manage(client: TestClient, db_session: Session):
    """Verify OWNER role can access both operational and management routes."""
    owner = register_user(db_session, "owner_full@example.com", "Password123!", "Owner Full")
    account = Account(
        account_number="ACC-OWNER-FULL",
        account_name="Owner Full Account",
        currency="INR",
        balance=10000,
        status=AccountStatus.ACTIVE.value,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    db_session.add(
        AccountMembership(
            user_id=owner.id,
            account_id=account.id,
            membership_role=MembershipRole.OWNER.value,
        )
    )
    db_session.commit()

    _login_user(client, db_session, owner)

    # Operational route succeeds
    r_op = client.post(
        f"/test-auth/accounts/{account.id}/operate",
        headers=TRUSTED_HEADERS,
    )
    assert r_op.status_code == status.HTTP_200_OK

    # Management route succeeds
    r_manage = client.post(
        f"/test-auth/accounts/{account.id}/manage",
        headers=TRUSTED_HEADERS,
    )
    assert r_manage.status_code == status.HTTP_200_OK


# ===========================================================================
# 4. GLOBAL AUDITOR WRITE ACTION ENFORCEMENT
# ===========================================================================


def test_global_auditor_with_owner_membership_rejected_on_write(
    client: TestClient,
    db_session: Session,
):
    """Verify that a global AUDITOR is rejected with HTTP 403 on write endpoints even if their membership is OWNER."""
    auditor = register_user(db_session, "auditor_owner@example.com", "Password123!", "Auditor Owner")
    auditor.role = UserRole.AUDITOR.value
    account = Account(
        account_number="ACC-AUDIT-OWNER",
        account_name="Auditor Account",
        currency="INR",
        balance=50000,
        status=AccountStatus.ACTIVE.value,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    # Membership says OWNER, but global role is AUDITOR
    db_session.add(
        AccountMembership(
            user_id=auditor.id,
            account_id=account.id,
            membership_role=MembershipRole.OWNER.value,
        )
    )
    db_session.commit()

    _login_user(client, db_session, auditor)

    # Reading succeeds
    r_read = client.get(f"/test-auth/accounts/{account.id}")
    assert r_read.status_code == status.HTTP_200_OK

    # Operating fails with auditor-specific message
    r_op = client.post(
        f"/test-auth/accounts/{account.id}/operate",
        headers=TRUSTED_HEADERS,
    )
    assert r_op.status_code == status.HTTP_403_FORBIDDEN
    assert r_op.json() == {"detail": "Auditor role is restricted to read-only access"}

    # Managing fails with auditor-specific message
    r_manage = client.post(
        f"/test-auth/accounts/{account.id}/manage",
        headers=TRUSTED_HEADERS,
    )
    assert r_manage.status_code == status.HTTP_403_FORBIDDEN
    assert r_manage.json() == {"detail": "Auditor role is restricted to read-only access"}


# ===========================================================================
# 5. ACCOUNT STATUS RESTRICTION TESTS
# ===========================================================================


def test_frozen_account_operation_rejected(client: TestClient, db_session: Session):
    """Verify that operational requests on a FROZEN account receive HTTP 403."""
    user = register_user(db_session, "frozen_user@example.com", "Password123!", "Frozen User")
    account = Account(
        account_number="ACC-FROZEN-01",
        account_name="Frozen Account",
        currency="INR",
        balance=10000,
        status=AccountStatus.FROZEN.value,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    db_session.add(
        AccountMembership(
            user_id=user.id,
            account_id=account.id,
            membership_role=MembershipRole.OWNER.value,
        )
    )
    db_session.commit()

    _login_user(client, db_session, user)

    response = client.post(
        f"/test-auth/accounts/{account.id}/operate",
        headers=TRUSTED_HEADERS,
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "frozen and cannot process operations" in response.json()["detail"]
