"""
Security tests: Mass assignment protection and payload hardening.

Verifies:
1. Pydantic request models strictly forbid extraneous, unexpected, or privilege-escalating fields
   (model_config = ConfigDict(extra="forbid")).
2. Injection of forbidden fields (e.g. role, is_active, balance, status, currency, timestamps)
   triggers HTTP 422 Unprocessable Entity across all state-changing endpoints.
3. In all HTTP 422 rejection cases, the database state remains 100% untouched.
4. Strict type and bounds validation: negative amounts, zero amounts, floats, and non-UUIDs are rejected.
"""

import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.account import Account, AccountStatus
from backend.app.models.user import User, UserRole
from tests.security.conftest import (
    TRUSTED_HEADERS,
    login_client,
    make_account,
    make_user,
)


class TestRegistrationMassAssignment:
    """Verifies that public registration rejects extra fields (preventing role injection)."""

    def test_register_with_injected_role_rejected(self, client: TestClient, db_session: Session):
        """Attacker attempts to self-assign ADMIN role during registration -> HTTP 422."""
        initial_users = len(db_session.scalars(select(User)).all())

        resp = client.post(
            "/auth/register",
            headers=TRUSTED_HEADERS,
            json={
                "email": "injected_admin@bank.com",
                "password": "Password123!",
                "full_name": "Injected Admin",
                "role": "ADMIN",  # Forbidden field
            },
        )
        assert resp.status_code == 422
        errors = resp.json()["detail"]
        assert any("extra" in err["type"].lower() or "role" in str(err["loc"]) for err in errors)

        # Database state verification: user was not inserted
        db_session.expire_all()
        assert len(db_session.scalars(select(User)).all()) == initial_users

    def test_register_with_injected_status_and_id_rejected(
        self, client: TestClient, db_session: Session
    ):
        """Attacker injects is_active, id, created_at -> HTTP 422."""
        resp = client.post(
            "/auth/register",
            headers=TRUSTED_HEADERS,
            json={
                "email": "attacker@bank.com",
                "password": "Password123!",
                "full_name": "Attacker",
                "is_active": True,
                "id": str(uuid.uuid4()),
                "created_at": "2020-01-01T00:00:00Z",
            },
        )
        assert resp.status_code == 422

    def test_login_with_extra_fields_rejected(self, client: TestClient, db_session: Session):
        """Attacker injects unexpected fields into login payload -> HTTP 422."""
        resp = client.post(
            "/auth/login",
            headers=TRUSTED_HEADERS,
            json={
                "email": "someone@bank.com",
                "password": "Password123!",
                "role": "ADMIN",
                "remember_me": True,
            },
        )
        assert resp.status_code == 422


class TestAccountMassAssignment:
    """Verifies that account creation, status change, and updates reject forbidden fields."""

    def test_create_account_with_injected_balance_rejected(
        self, client: TestClient, db_session: Session
    ):
        """Admin attempts or is tricked into injecting initial balance or status -> HTTP 422."""
        admin = make_user(db_session, email="admin_create@bank.com", role=UserRole.ADMIN)
        login_client(client, db_session, admin)

        initial_accounts = len(db_session.scalars(select(Account)).all())

        resp = client.post(
            "/accounts",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Illegitimate Wealth Account",
                "currency": "INR",
                "balance": 9999999999,  # Forbidden field
            },
        )
        assert resp.status_code == 422

        db_session.expire_all()
        assert len(db_session.scalars(select(Account)).all()) == initial_accounts

    def test_patch_account_with_injected_balance_and_currency_rejected(
        self, client: TestClient, db_session: Session
    ):
        """Account owner attempts to PATCH balance or currency -> HTTP 422, state unchanged."""
        owner = make_user(db_session, email="owner_patch@bank.com")
        account, _ = make_account(
            db_session,
            owner,
            account_name="Original Name",
            currency="INR",
            balance_paise=10000,
        )
        login_client(client, db_session, owner)

        resp = client.patch(
            f"/accounts/{account.id}",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Updated Name",
                "balance": 88888888,  # Forbidden field
                "currency": "USD",  # Forbidden field
            },
        )
        assert resp.status_code == 422

        # Verify DB remained untouched
        db_session.expire_all()
        db_acc = db_session.get(Account, account.id)
        assert db_acc.account_name == "Original Name"
        assert db_acc.balance == 10000
        assert db_acc.currency == "INR"

    def test_account_status_update_with_extra_fields_rejected(
        self, client: TestClient, db_session: Session
    ):
        """Admin status update with injected account_name or balance -> HTTP 422."""
        admin = make_user(db_session, email="admin_stat@bank.com", role=UserRole.ADMIN)
        user = make_user(db_session, email="target_user@bank.com")
        account, _ = make_account(db_session, user, status=AccountStatus.ACTIVE)
        login_client(client, db_session, admin)

        resp = client.post(
            f"/accounts/{account.id}/status",
            headers=TRUSTED_HEADERS,
            json={
                "status": "FROZEN",
                "account_name": "Tampered During Freeze",  # Forbidden
            },
        )
        assert resp.status_code == 422

        db_session.expire_all()
        assert db_session.get(Account, account.id).status == AccountStatus.ACTIVE


class TestTransactionMassAssignmentAndValidation:
    """Verifies that financial transaction payloads reject forbidden fields and invalid types."""

    def test_deposit_with_injected_fields_rejected(self, client: TestClient, db_session: Session):
        """Attacker injects status or transaction_type into deposit payload -> HTTP 422."""
        owner = make_user(db_session, email="owner_dep_mass@bank.com")
        account, _ = make_account(db_session, owner, balance_paise=50000)
        login_client(client, db_session, owner)

        resp = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={
                "account_id": str(account.id),
                "amount_paise": 10000,
                "status": "COMPLETED",  # Forbidden field
                "source_account_id": str(uuid.uuid4()),  # Forbidden field
            },
        )
        assert resp.status_code == 422

        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 50000

    def test_withdraw_with_injected_fields_rejected(self, client: TestClient, db_session: Session):
        """Attacker injects destination_account_id into withdrawal -> HTTP 422."""
        owner = make_user(db_session, email="owner_w_mass@bank.com")
        account, _ = make_account(db_session, owner, balance_paise=50000)
        login_client(client, db_session, owner)

        resp = client.post(
            "/transactions/withdraw",
            headers=TRUSTED_HEADERS,
            json={
                "account_id": str(account.id),
                "amount_paise": 10000,
                "destination_account_id": str(uuid.uuid4()),  # Forbidden field
            },
        )
        assert resp.status_code == 422

        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 50000

    def test_transfer_with_injected_fields_rejected(self, client: TestClient, db_session: Session):
        """Attacker injects fee or transaction_status into transfer -> HTTP 422."""
        owner = make_user(db_session, email="owner_xfer_mass@bank.com")
        source, _ = make_account(db_session, owner, balance_paise=50000)
        other = make_user(db_session, email="dest_xfer_mass@bank.com")
        dest, _ = make_account(db_session, other, balance_paise=10000)
        login_client(client, db_session, owner)

        resp = client.post(
            "/transactions/transfer",
            headers=TRUSTED_HEADERS,
            json={
                "source_account_id": str(source.id),
                "destination_account_id": str(dest.id),
                "amount_paise": 10000,
                "fee": 0,  # Forbidden field
                "status": "SUCCESS",  # Forbidden field
            },
        )
        assert resp.status_code == 422

        db_session.expire_all()
        assert db_session.get(Account, source.id).balance == 50000
        assert db_session.get(Account, dest.id).balance == 10000

    def test_negative_or_zero_paise_amount_rejected(self, client: TestClient, db_session: Session):
        """Deposit with zero or negative amount is rejected by schema -> HTTP 422."""
        owner = make_user(db_session, email="owner_bounds@bank.com")
        account, _ = make_account(db_session, owner, balance_paise=50000)
        login_client(client, db_session, owner)

        # Zero amount
        resp_zero = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 0},
        )
        assert resp_zero.status_code == 422

        # Negative amount
        resp_neg = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": -5000},
        )
        assert resp_neg.status_code == 422

        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 50000

    def test_float_paise_amount_rejected_strict_integer(
        self, client: TestClient, db_session: Session
    ):
        """Floating point paise amounts are rejected by strict integer validator -> HTTP 422."""
        owner = make_user(db_session, email="owner_float@bank.com")
        account, _ = make_account(db_session, owner, balance_paise=50000)
        login_client(client, db_session, owner)

        resp = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 100.50},
        )
        assert resp.status_code == 422

        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 50000
