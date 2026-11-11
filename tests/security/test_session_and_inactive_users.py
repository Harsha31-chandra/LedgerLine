"""
Security tests: Session validation, lifecycle, inactive user handling, and revoked memberships.

Verifies:
1. Missing, malformed, expired, and revoked session tokens are rejected with HTTP 401.
2. Inactive users (is_active=False) cannot authenticate (HTTP 403) or use existing sessions (HTTP 403).
3. Deactivated users cannot perform any read or write actions across all routes.
4. Revoked account memberships result in HTTP 404 (anti-IDOR defense).
5. In all rejection scenarios, database state and financial balances remain completely untouched.
"""

from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.session import Session as SessionModel
from backend.app.models.user import User, UserRole
from backend.app.services.auth_service import create_session, hash_session_token, revoke_session
from tests.security.conftest import (
    TRUSTED_HEADERS,
    login_client,
    make_account,
    make_user,
)


class TestSessionValidationAndLifecycle:
    """Verifies that missing, corrupted, expired, or revoked sessions are rejected with HTTP 401."""

    def test_missing_session_cookie_rejected(self, client: TestClient, db_session: Session):
        """Request without session cookie receives HTTP 401."""
        client.cookies.clear()
        resp = client.get("/auth/me", headers=TRUSTED_HEADERS)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"

    def test_malformed_session_token_rejected(self, client: TestClient, db_session: Session):
        """Request with unknown or forged session token receives HTTP 401."""
        client.cookies.set(settings.session_cookie_name, "forged_random_token_string_12345")
        resp = client.get("/auth/me", headers=TRUSTED_HEADERS)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid session token"

    def test_expired_session_rejected(self, client: TestClient, db_session: Session):
        """Request with an expired session token receives HTTP 401."""
        user = make_user(db_session, email="expired_user@bank.com")
        sess_res = create_session(db_session, user)

        # Manually expire the session in the database
        db_sess = db_session.get(SessionModel, sess_res.session.id)
        db_sess.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db_session.commit()

        client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
        resp = client.get("/auth/me", headers=TRUSTED_HEADERS)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Session has expired"

    def test_revoked_session_rejected(self, client: TestClient, db_session: Session):
        """Request with a revoked session token receives HTTP 401."""
        user = make_user(db_session, email="revoked_user@bank.com")
        sess_res = create_session(db_session, user)

        # Explicitly revoke the session
        revoke_session(db_session, sess_res.raw_token)

        client.cookies.set(settings.session_cookie_name, sess_res.raw_token)
        resp = client.get("/auth/me", headers=TRUSTED_HEADERS)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Session has been revoked"

    def test_logout_invalidates_session(self, client: TestClient, db_session: Session):
        """Logging out revokes session in DB and prevents further access."""
        user = make_user(db_session, email="logout_user@bank.com")
        raw_token = login_client(client, db_session, user)

        # Call logout endpoint
        resp_logout = client.post("/auth/logout", headers=TRUSTED_HEADERS)
        assert resp_logout.status_code == 200

        # Subsequet access must fail
        resp_after = client.get("/auth/me", headers=TRUSTED_HEADERS)
        assert resp_after.status_code == 401


class TestInactiveUserRejection:
    """Verifies that deactivated users cannot authenticate or execute any operations."""

    def test_inactive_user_cannot_login(self, client: TestClient, db_session: Session):
        """Deactivated user attempting login receives HTTP 403."""
        user = make_user(
            db_session,
            email="inactive_login@bank.com",
            password="ValidPassword123!",
            is_active=False,
        )

        resp = client.post(
            "/auth/login",
            headers=TRUSTED_HEADERS,
            json={"email": "inactive_login@bank.com", "password": "ValidPassword123!"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "User account is inactive"

    def test_deactivated_user_with_prior_session_blocked(
        self, client: TestClient, db_session: Session
    ):
        """User who is deactivated after session creation is immediately blocked on all routes."""
        user = make_user(db_session, email="deactivated_later@bank.com")
        account, _ = make_account(db_session, user, balance_paise=50000)
        login_client(client, db_session, user)

        # Deactivate user in DB
        user.is_active = False
        db_session.commit()

        # 1. /auth/me -> HTTP 403
        resp_me = client.get("/auth/me", headers=TRUSTED_HEADERS)
        assert resp_me.status_code == 403
        assert resp_me.json()["detail"] == "User account is inactive"

        # 2. /accounts -> HTTP 403
        resp_acc = client.get("/accounts", headers=TRUSTED_HEADERS)
        assert resp_acc.status_code == 403

        # 3. /accounts/{id} -> HTTP 403
        resp_detail = client.get(f"/accounts/{account.id}", headers=TRUSTED_HEADERS)
        assert resp_detail.status_code == 403

        # 4. /transactions/deposit -> HTTP 403
        resp_dep = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 1000},
        )
        assert resp_dep.status_code == 403

        # 5. /transactions/withdraw -> HTTP 403
        resp_with = client.post(
            "/transactions/withdraw",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 1000},
        )
        assert resp_with.status_code == 403

        # 6. /accounts/{id}/statement -> HTTP 403
        resp_stmt = client.get(f"/accounts/{account.id}/statement", headers=TRUSTED_HEADERS)
        assert resp_stmt.status_code == 403

        # Verify DB balance remains strictly unchanged
        db_session.expire_all()
        assert db_session.get(Account, account.id).balance == 50000


class TestRevokedMembershipBehavior:
    """Verifies that removing account membership immediately returns HTTP 404 anti-IDOR."""

    def test_revoked_membership_returns_404_on_all_account_endpoints(
        self, client: TestClient, db_session: Session
    ):
        """User whose membership was revoked cannot view or operate account -> HTTP 404."""
        user = make_user(db_session, email="revoked_member@bank.com")
        account, membership = make_account(db_session, user, balance_paise=100000)
        login_client(client, db_session, user)

        # Revoke/delete the membership record
        db_session.delete(membership)
        db_session.commit()

        # 1. GET /accounts/{id} -> HTTP 404
        resp_get = client.get(f"/accounts/{account.id}", headers=TRUSTED_HEADERS)
        assert resp_get.status_code == 404
        assert resp_get.json()["detail"] == "Account not found"

        # 2. PATCH /accounts/{id} -> HTTP 404
        resp_patch = client.patch(
            f"/accounts/{account.id}",
            headers=TRUSTED_HEADERS,
            json={"account_name": "New Name Without Membership"},
        )
        assert resp_patch.status_code == 404

        # 3. POST /transactions/deposit -> HTTP 404
        resp_dep = client.post(
            "/transactions/deposit",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 1000},
        )
        assert resp_dep.status_code == 404

        # 4. POST /transactions/withdraw -> HTTP 404
        resp_with = client.post(
            "/transactions/withdraw",
            headers=TRUSTED_HEADERS,
            json={"account_id": str(account.id), "amount_paise": 1000},
        )
        assert resp_with.status_code == 404

        # 5. GET /accounts/{id}/statement -> HTTP 404
        resp_stmt = client.get(f"/accounts/{account.id}/statement", headers=TRUSTED_HEADERS)
        assert resp_stmt.status_code == 404

        # Verify DB balance and name untouched
        db_session.expire_all()
        db_acc = db_session.get(Account, account.id)
        assert db_acc.balance == 100000
        assert db_acc.account_name == "Operating Account"
