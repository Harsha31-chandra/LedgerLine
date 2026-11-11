"""
Security tests: Role enforcement, privilege escalation barriers, and Auditor read-only constraints.

Verifies:
1. Global role boundaries:
   - HOLDER and AUDITOR principals cannot access Admin-only endpoints (POST /accounts,
     POST /accounts/{id}/status, GET /admin/accounts) -> HTTP 403.
   - DB state is verified to be untouched on rejected admin calls.
2. Auditor read-only restrictions:
   - AUDITOR principals are strictly prohibited from mutating financial or account state
     (deposit, withdraw, transfer, patch account) -> HTTP 403.
   - Global AUDITOR restriction overrides account membership role: even if an auditor is
     explicitly assigned OWNER or OPERATOR membership, write operations are blocked.
   - AUDITOR principals can read account details, ledger statements, and transactions -> HTTP 200.
3. Account-level membership role enforcement:
   - VIEWER members cannot perform operational mutations (deposit, withdraw, transfer) or PATCH -> HTTP 403.
   - OPERATOR members can perform operational mutations but cannot update account metadata (PATCH) -> HTTP 403.
   - In all forbidden mutations, database balances and attributes remain completely unaltered.
"""

import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import MembershipRole
from backend.app.models.transaction import Transaction
from backend.app.models.user import UserRole
from tests.security.conftest import (
    TRUSTED_HEADERS,
    login_client,
    make_account,
    make_user,
)


class TestGlobalAdminRoleEnforcement:
    """Verifies that non-admin users cannot access administrative endpoints."""

    def test_holder_cannot_create_account(self, client: TestClient, db_session: Session):
        """HOLDER attempting POST /accounts must receive 403 and create no account."""
        holder = make_user(db_session, email="holder@bank.com", role=UserRole.HOLDER)
        login_client(client, db_session, holder)

        initial_count = len(db_session.scalars(select(Account)).all())

        resp = client.post(
            "/accounts",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Unauthorized Account",
                "currency": "INR",
                "owner_user_id": str(holder.id),
            },
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Insufficient role permissions"

        # Database state verification: no new account inserted
        db_session.expire_all()
        current_count = len(db_session.scalars(select(Account)).all())
        assert current_count == initial_count

    def test_auditor_cannot_create_account(self, client: TestClient, db_session: Session):
        """AUDITOR attempting POST /accounts must receive 403 and create no account."""
        auditor = make_user(db_session, email="auditor_admin@bank.com", role=UserRole.AUDITOR)
        login_client(client, db_session, auditor)

        initial_count = len(db_session.scalars(select(Account)).all())

        resp = client.post(
            "/accounts",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Auditor Created Account",
                "currency": "INR",
                "owner_user_id": str(auditor.id),
            },
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Insufficient role permissions"

        db_session.expire_all()
        assert len(db_session.scalars(select(Account)).all()) == initial_count

    def test_holder_cannot_update_account_status(self, client: TestClient, db_session: Session):
        """HOLDER attempting POST /accounts/{id}/status must receive 403 and not modify status."""
        holder = make_user(db_session, email="holder_freeze@bank.com", role=UserRole.HOLDER)
        account, _ = make_account(db_session, holder, status=AccountStatus.ACTIVE)
        login_client(client, db_session, holder)

        resp = client.post(
            f"/accounts/{account.id}/status",
            headers=TRUSTED_HEADERS,
            json={"status": "FROZEN"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Insufficient role permissions"

        # Verify DB status is still ACTIVE
        db_session.expire_all()
        db_acc = db_session.get(Account, account.id)
        assert db_acc.status == AccountStatus.ACTIVE

    def test_holder_cannot_access_admin_accounts_registry(
        self, client: TestClient, db_session: Session
    ):
        """HOLDER attempting GET /admin/accounts must receive 403."""
        holder = make_user(db_session, email="holder_registry@bank.com", role=UserRole.HOLDER)
        login_client(client, db_session, holder)

        resp = client.get("/admin/accounts", headers=TRUSTED_HEADERS)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Insufficient role permissions"

    def test_auditor_cannot_access_admin_accounts_registry(
        self, client: TestClient, db_session: Session
    ):
        """AUDITOR attempting GET /admin/accounts must receive 403."""
        auditor = make_user(db_session, email="auditor_registry@bank.com", role=UserRole.AUDITOR)
        login_client(client, db_session, auditor)

        resp = client.get("/admin/accounts", headers=TRUSTED_HEADERS)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Insufficient role permissions"

    def test_admin_can_access_admin_accounts_registry(
        self, client: TestClient, db_session: Session
    ):
        """ADMIN attempting GET /admin/accounts receives 200 with accounts list."""
        admin = make_user(db_session, email="admin_ok@bank.com", role=UserRole.ADMIN)
        user = make_user(db_session, email="cust_ok@bank.com", role=UserRole.HOLDER)
        account, _ = make_account(db_session, user, account_name="Customer Checking")
        login_client(client, db_session, admin)

        resp = client.get("/admin/accounts", headers=TRUSTED_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        matching = [a for a in data if a["id"] == str(account.id)]
        assert len(matching) == 1
        assert matching[0]["account_name"] == "Customer Checking"


class TestAuditorReadOnlyRestrictions:
    """Verifies that AUDITOR principals are strictly read-only and cannot mutate state."""

    def test_auditor_cannot_deposit_even_as_owner(self, client: TestClient, db_session: Session):
        """AUDITOR assigned OWNER role cannot deposit funds -> HTTP 403, 0 balance change."""
        auditor = make_user(db_session, email="auditor_deposit@bank.com", role=UserRole.AUDITOR)
        account, _ = make_account(
            db_session,
            auditor,
            balance_paise=50000,
            membership_role=MembershipRole.OWNER,
        )
        login_client(client, db_session, auditor)

        resp = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 10000, "description": "Deposit attempt"},
        )
        assert resp.status_code == 403
        assert "Auditor" in resp.json()["detail"]

        # Verify DB balance remains completely unchanged
        db_session.expire_all()
        db_acc = db_session.get(Account, account.id)
        assert db_acc.balance == 50000

    def test_auditor_cannot_withdraw_even_as_owner(self, client: TestClient, db_session: Session):
        """AUDITOR assigned OWNER role cannot withdraw funds -> HTTP 403, 0 balance change."""
        auditor = make_user(db_session, email="auditor_withdraw@bank.com", role=UserRole.AUDITOR)
        account, _ = make_account(
            db_session,
            auditor,
            balance_paise=50000,
            membership_role=MembershipRole.OWNER,
        )
        login_client(client, db_session, auditor)

        resp = client.post(
            "/transactions/withdraw",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 10000, "description": "Withdraw attempt"},
        )
        assert resp.status_code == 403
        assert "Auditor" in resp.json()["detail"]

        db_session.expire_all()
        db_acc = db_session.get(Account, account.id)
        assert db_acc.balance == 50000

    def test_auditor_cannot_transfer_even_as_owner(self, client: TestClient, db_session: Session):
        """AUDITOR cannot transfer funds -> HTTP 403, 0 balance change."""
        auditor = make_user(db_session, email="auditor_xfer@bank.com", role=UserRole.AUDITOR)
        source, _ = make_account(db_session, auditor, balance_paise=50000, membership_role=MembershipRole.OWNER)

        dest_user = make_user(db_session, email="dest_auditor@bank.com", role=UserRole.HOLDER)
        dest, _ = make_account(db_session, dest_user, balance_paise=10000)

        login_client(client, db_session, auditor)

        resp = client.post(
            "/transactions/transfer",
            headers=TRUSTED_HEADERS,
            json={
                "source_account_id": str(source.id),
                "destination_account_id": str(dest.id),
                "amount_paise": 10000,
                "description": "Auditor transfer attempt",
            },
        )
        assert resp.status_code == 403
        assert "Auditor" in resp.json()["detail"]

        db_session.expire_all()
        assert db_session.get(Account, source.id).balance == 50000
        assert db_session.get(Account, dest.id).balance == 10000

    def test_auditor_cannot_patch_account_metadata(self, client: TestClient, db_session: Session):
        """AUDITOR cannot PATCH account details -> HTTP 403, name unchanged."""
        auditor = make_user(db_session, email="auditor_patch@bank.com", role=UserRole.AUDITOR)
        account, _ = make_account(
            db_session,
            auditor,
            account_name="Original Auditor Account",
            membership_role=MembershipRole.OWNER,
        )
        login_client(client, db_session, auditor)

        resp = client.patch(
            f"/accounts/{account.id}",
            headers=TRUSTED_HEADERS,
            json={"account_name": "Tampered Account Name"},
        )
        assert resp.status_code == 403
        assert "Auditor" in resp.json()["detail"]

        db_session.expire_all()
        assert db_session.get(Account, account.id).account_name == "Original Auditor Account"

    def test_auditor_can_read_account_details_and_statements(
        self, client: TestClient, db_session: Session
    ):
        """AUDITOR with VIEWER or OWNER membership CAN read account details and statement -> HTTP 200."""
        auditor = make_user(db_session, email="auditor_reader@bank.com", role=UserRole.AUDITOR)
        account, _ = make_account(
            db_session,
            auditor,
            account_name="Audit Review Account",
            balance_paise=75000,
            membership_role=MembershipRole.VIEWER,
        )
        login_client(client, db_session, auditor)

        # 1. Read account detail
        resp_acc = client.get(f"/accounts/{account.id}", headers=TRUSTED_HEADERS)
        assert resp_acc.status_code == 200
        assert resp_acc.json()["account_name"] == "Audit Review Account"
        assert resp_acc.json()["balance"] == 75000

        # 2. Read statement
        resp_stmt = client.get(f"/accounts/{account.id}/statement", headers=TRUSTED_HEADERS)
        assert resp_stmt.status_code == 200
        assert resp_stmt.json()["account_id"] == str(account.id)


class TestAccountMembershipRoleEnforcement:
    """Verifies granular account membership roles (OWNER, OPERATOR, VIEWER)."""

    def test_viewer_cannot_deposit(self, client: TestClient, db_session: Session):
        """User with VIEWER membership cannot execute deposit -> HTTP 403."""
        viewer = make_user(db_session, email="viewer_dep@bank.com")
        account, _ = make_account(
            db_session,
            viewer,
            balance_paise=10000,
            membership_role=MembershipRole.VIEWER,
        )
        login_client(client, db_session, viewer)

        resp = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 5000, "description": "Viewer deposit"},
        )
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 10000

    def test_viewer_cannot_withdraw(self, client: TestClient, db_session: Session):
        """User with VIEWER membership cannot execute withdrawal -> HTTP 403."""
        viewer = make_user(db_session, email="viewer_with@bank.com")
        account, _ = make_account(
            db_session,
            viewer,
            balance_paise=10000,
            membership_role=MembershipRole.VIEWER,
        )
        login_client(client, db_session, viewer)

        resp = client.post(
            "/transactions/withdraw",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 5000, "description": "Viewer withdrawal"},
        )
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 10000

    def test_viewer_cannot_transfer(self, client: TestClient, db_session: Session):
        """User with VIEWER membership on source account cannot transfer -> HTTP 403."""
        viewer = make_user(db_session, email="viewer_tx@bank.com")
        source, _ = make_account(
            db_session,
            viewer,
            balance_paise=10000,
            membership_role=MembershipRole.VIEWER,
        )
        other = make_user(db_session, email="dest_view@bank.com")
        dest, _ = make_account(db_session, other, balance_paise=5000)

        login_client(client, db_session, viewer)

        resp = client.post(
            "/transactions/transfer",
            headers=TRUSTED_HEADERS,
            json={
                "source_account_id": str(source.id),
                "destination_account_id": str(dest.id),
                "amount_paise": 2000,
                "description": "Viewer transfer",
            },
        )
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

        db_session.expire_all()
        assert db_session.get(Account, source.id).balance == 10000
        assert db_session.get(Account, dest.id).balance == 5000

    def test_operator_cannot_patch_account_metadata(self, client: TestClient, db_session: Session):
        """User with OPERATOR membership cannot PATCH account metadata -> HTTP 403 (requires OWNER)."""
        operator = make_user(db_session, email="operator_patch@bank.com")
        account, _ = make_account(
            db_session,
            operator,
            account_name="Unchangeable Name",
            membership_role=MembershipRole.OPERATOR,
        )
        login_client(client, db_session, operator)

        resp = client.patch(
            f"/accounts/{account.id}",
            headers=TRUSTED_HEADERS,
            json={"account_name": "New Name Attempt"},
        )
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

        db_session.expire_all()
        assert db_session.get(Account, account.id).account_name == "Unchangeable Name"

    def test_operator_can_operate_financial_mutations(
        self, client: TestClient, db_session: Session
    ):
        """User with OPERATOR membership CAN deposit and withdraw -> HTTP 200."""
        operator = make_user(db_session, email="operator_valid@bank.com")
        account, _ = make_account(
            db_session,
            operator,
            balance_paise=50000,
            membership_role=MembershipRole.OPERATOR,
        )
        login_client(client, db_session, operator)

        # Deposit
        resp_dep = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 20000, "description": "Operator deposit"},
        )
        assert resp_dep.status_code == 200

        # Verify DB balance
        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 70000

        # Withdraw
        resp_with = client.post(
            "/transactions/withdraw",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 15000, "description": "Operator withdraw"},
        )
        assert resp_with.status_code == 200

        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 55000
