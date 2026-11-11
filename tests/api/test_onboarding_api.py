"""
Tests for self-service account onboarding and demo initial deposit logic.
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

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app, base_url="http://testserver")
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def make_user(
    db: Session,
    email: str = "holder@example.com",
    role: UserRole = UserRole.HOLDER,
) -> User:
    u = register_user(db, email, "Password123!", "Test User")
    u.role = role.value
    db.commit()
    db.refresh(u)
    return u


def login_client(client: TestClient, db: Session, user: User) -> None:
    session_obj, raw_token = create_session(db, user)
    client.cookies.set(settings.session_cookie_name, raw_token)


class TestAccountOnboardingAPI:
    """Verifies POST /accounts/onboarding behavior, demo deposit handling, and anti-abuse controls."""

    def test_onboarding_account_without_initial_deposit(
        self, client: TestClient, db_session: Session
    ):
        """A new holder can open their first account with zero initial balance."""
        user = make_user(db_session, email="onboard_zero@test.com", role=UserRole.HOLDER)
        login_client(client, db_session, user)

        resp = client.post(
            "/accounts/onboarding",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Personal Checking",
                "currency": "INR",
                "account_type": "Current Account",
                "initial_deposit_paise": 0,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["account_name"] == "Personal Checking"
        assert data["balance"] == 0
        assert data["membership_role"] == "OWNER"
        assert data["status"] == "ACTIVE"

    def test_onboarding_account_with_valid_demo_deposit(
        self, client: TestClient, db_session: Session
    ):
        """A new holder can open an account with ₹10,000 (1,000,000 paise) sample demo deposit."""
        user = make_user(db_session, email="onboard_demo@test.com", role=UserRole.HOLDER)
        login_client(client, db_session, user)

        resp = client.post(
            "/accounts/onboarding",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Primary Savings",
                "currency": "INR",
                "account_type": "Savings Account",
                "initial_deposit_paise": 1_000_000,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["account_name"] == "Primary Savings"
        assert data["balance"] == 1_000_000
        assert data["membership_role"] == "OWNER"

        # Verify double-entry ledger entries exist and balance
        account_id = data["id"]
        stmt_resp = client.get(f"/accounts/{account_id}/statement", headers=TRUSTED_HEADERS)
        assert stmt_resp.status_code == 200
        stmt = stmt_resp.json()
        assert stmt["balance_paise"] == 1_000_000
        assert len(stmt["entries"]) == 1
        assert stmt["entries"][0]["entry_type"] == "CREDIT"
        assert stmt["entries"][0]["amount_paise"] == 1_000_000

    def test_repeated_demo_funds_claim_prohibited(
        self, client: TestClient, db_session: Session
    ):
        """A user cannot claim demo funds more than once through repeated account creation."""
        user = make_user(db_session, email="abuse_demo@test.com", role=UserRole.HOLDER)
        login_client(client, db_session, user)

        # 1. First account creation with demo deposit succeeds
        resp1 = client.post(
            "/accounts/onboarding",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "First Account",
                "currency": "INR",
                "initial_deposit_paise": 1_000_000,
            },
        )
        assert resp1.status_code == 201

        # 2. Second account creation with demo deposit is rejected
        resp2 = client.post(
            "/accounts/onboarding",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Second Account",
                "currency": "INR",
                "initial_deposit_paise": 500_000,
            },
        )
        assert resp2.status_code == 400
        assert "already been claimed" in resp2.json()["detail"]

        # 3. But opening a second account with 0 balance is permitted
        resp3 = client.post(
            "/accounts/onboarding",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Second Account No Deposit",
                "currency": "INR",
                "initial_deposit_paise": 0,
            },
        )
        assert resp3.status_code == 201

    def test_auditor_cannot_onboard_account(
        self, client: TestClient, db_session: Session
    ):
        """Auditor role is restricted to read-only access and cannot open accounts."""
        auditor = make_user(db_session, email="auditor_onboard@test.com", role=UserRole.AUDITOR)
        login_client(client, db_session, auditor)

        resp = client.post(
            "/accounts/onboarding",
            headers=TRUSTED_HEADERS,
            json={"account_name": "Auditor Account", "currency": "INR"},
        )
        assert resp.status_code == 403
        assert "read-only" in resp.json()["detail"].lower()

    def test_list_transactions_scoping(
        self, client: TestClient, db_session: Session
    ):
        """GET /transactions returns only transactions relevant to the user's accounts."""
        user = make_user(db_session, email="tx_scope_user@test.com", role=UserRole.HOLDER)
        login_client(client, db_session, user)

        # Open an account with demo deposit
        resp = client.post(
            "/accounts/onboarding",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Tx Scope Account",
                "currency": "INR",
                "initial_deposit_paise": 500_000,
            },
        )
        assert resp.status_code == 201

        # Query GET /transactions
        tx_resp = client.get("/transactions", headers=TRUSTED_HEADERS)
        assert tx_resp.status_code == 200
        txs = tx_resp.json()
        assert len(txs) >= 1
        assert txs[0]["amount_paise"] == 500_000
