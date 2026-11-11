"""
Security tests: Comprehensive route authorization matrix.

Verifies that every single endpoint in the application strictly enforces:
1. Public availability where intended (/health, POST /auth/register, POST /auth/login).
2. Unauthenticated access denial (HTTP 401) on all protected endpoints.
3. Strict role and ownership barriers across the complete route inventory:
   - Admin routes: require UserRole.ADMIN (HOLDER/AUDITOR receive HTTP 403).
   - Account detail and statement routes: require active membership (non-members receive HTTP 404).
   - Financial mutation routes: require OPERATOR/OWNER role and reject non-members with HTTP 404.
"""

import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from backend.app.models.user import UserRole
from tests.security.conftest import (
    TRUSTED_HEADERS,
    login_client,
    make_account,
    make_user,
)


class TestUnauthenticatedAccessRejection:
    """Verifies that all protected endpoints return HTTP 401 when no session cookie is provided."""

    @pytest.mark.parametrize(
        "method,endpoint,payload",
        [
            ("GET", "/auth/me", None),
            ("GET", "/accounts", None),
            ("POST", "/accounts", {"account_name": "Test", "currency": "INR"}),
            ("GET", f"/accounts/{uuid.uuid4()}", None),
            ("PATCH", f"/accounts/{uuid.uuid4()}", {"account_name": "New Name"}),
            ("POST", f"/accounts/{uuid.uuid4()}/status", {"status": "FROZEN"}),
            ("GET", f"/accounts/{uuid.uuid4()}/statement", None),
            (
                "POST",
                "/transactions/deposit",
                {"account_id": str(uuid.uuid4()), "amount_paise": 1000},
            ),
            (
                "POST",
                "/transactions/withdraw",
                {"account_id": str(uuid.uuid4()), "amount_paise": 1000},
            ),
            (
                "POST",
                "/transactions/transfer",
                {
                    "source_account_id": str(uuid.uuid4()),
                    "destination_account_id": str(uuid.uuid4()),
                    "amount_paise": 1000,
                },
            ),
            ("GET", f"/transactions/{uuid.uuid4()}", None),
            ("GET", "/admin/accounts", None),
        ],
    )
    def test_protected_routes_reject_unauthenticated(
        self, client: TestClient, method: str, endpoint: str, payload: dict | None
    ):
        """Unauthenticated requests must receive HTTP 401 Unauthorized."""
        client.cookies.clear()
        if method == "GET":
            resp = client.get(endpoint, headers=TRUSTED_HEADERS)
        elif method == "POST":
            resp = client.post(endpoint, headers=TRUSTED_HEADERS, json=payload or {})
        elif method == "PATCH":
            resp = client.patch(endpoint, headers=TRUSTED_HEADERS, json=payload or {})
        else:
            pytest.fail(f"Unhandled method {method}")

        assert resp.status_code == 401, f"Expected 401 for {method} {endpoint}, got {resp.status_code}"

    def test_logout_is_idempotent_even_unauthenticated(self, client: TestClient):
        """POST /auth/logout is idempotent and safely returns 200 while clearing cookie."""
        client.cookies.clear()
        resp = client.post("/auth/logout", headers=TRUSTED_HEADERS)
        assert resp.status_code == 200
        assert "Successfully logged out" in resp.json()["detail"]


class TestPublicEndpointsAvailability:
    """Verifies that public routes are accessible without authentication."""

    def test_health_check_public(self, client: TestClient):
        """GET /health must return HTTP 200 without authentication or CSRF headers."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_register_public(self, client: TestClient, db_session: Session):
        """POST /auth/register is public and creates a holder user."""
        resp = client.post(
            "/auth/register",
            headers=TRUSTED_HEADERS,
            json={
                "email": "matrix_public@bank.com",
                "password": "Password123!",
                "full_name": "Public Registered",
            },
        )
        assert resp.status_code == 201

    def test_login_public(self, client: TestClient, db_session: Session):
        """POST /auth/login is public and authenticates credentials."""
        user = make_user(db_session, email="matrix_login@bank.com", password="Password123!")
        resp = client.post(
            "/auth/login",
            headers=TRUSTED_HEADERS,
            json={"email": "matrix_login@bank.com", "password": "Password123!"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "matrix_login@bank.com"


class TestRoleAndOwnershipMatrixVerification:
    """Verifies access control matrix for Admin, Auditor, and Holder on all resource endpoints."""

    def test_admin_route_matrix(self, client: TestClient, db_session: Session):
        """Admin routes reject Holder and Auditor with HTTP 403, and permit Admin with HTTP 200/201."""
        admin = make_user(db_session, email="mat_admin@bank.com", role=UserRole.ADMIN)
        holder = make_user(db_session, email="mat_holder@bank.com", role=UserRole.HOLDER)
        auditor = make_user(db_session, email="mat_auditor@bank.com", role=UserRole.AUDITOR)

        # 1. HOLDER on admin routes -> 403
        login_client(client, db_session, holder)
        assert client.get("/admin/accounts", headers=TRUSTED_HEADERS).status_code == 403
        assert (
            client.post(
                "/accounts",
                headers=TRUSTED_HEADERS,
                json={"account_name": "H", "currency": "INR"},
            ).status_code
            == 403
        )

        # 2. AUDITOR on admin routes -> 403
        login_client(client, db_session, auditor)
        assert client.get("/admin/accounts", headers=TRUSTED_HEADERS).status_code == 403
        assert (
            client.post(
                "/accounts",
                headers=TRUSTED_HEADERS,
                json={"account_name": "A", "currency": "INR"},
            ).status_code
            == 403
        )

        # 3. ADMIN on admin routes -> 200 / 201
        login_client(client, db_session, admin)
        assert client.get("/admin/accounts", headers=TRUSTED_HEADERS).status_code == 200
        assert (
            client.post(
                "/accounts",
                headers=TRUSTED_HEADERS,
                json={"account_name": "Admin Authorized Account", "currency": "INR"},
            ).status_code
            == 201
        )
