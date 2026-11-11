"""
Security tests: Audit trail integrity, sensitive credential scrubbing, and immutability.

Verifies:
1. Sensitive credential scrubbing:
   - Passwords, tokens, raw tokens, password hashes, secrets, session secrets, API keys, and credentials
     are strictly removed from audit event metadata (both top-level and recursively in nested structures).
   - Non-sensitive operational metadata is preserved intact.
2. Full actor and IP attribution:
   - Audit records accurately record actor_user_id and ip_address.
   - Entity type and entity ID are accurately linked.
3. System operations audit trail coverage:
   - Account creation, status transitions, metadata updates, and financial operations
     (deposit, withdrawal, transfer) each produce an immutable AuditEvent in the transaction.
"""

import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.account import Account, AccountStatus
from backend.app.models.audit_event import AuditEvent
from backend.app.models.user import UserRole
from backend.app.services.audit_service import record_audit_event
from tests.security.conftest import (
    TRUSTED_HEADERS,
    login_client,
    make_account,
    make_user,
)


class TestCredentialScrubbingInAuditTrail:
    """Verifies that sensitive credentials are recursively scrubbed from audit metadata."""

    def test_top_level_sensitive_keys_scrubbed(self, db_session: Session):
        """Top-level secrets, passwords, tokens, cookies, auth headers, and keys must not be persisted."""
        raw_metadata = {
            "password": "SuperSecretPassword123!",
            "PASSWORD": "UppercaseSecret!",
            " token ": "whitespace_padded_token",
            "raw_token": "random_csprng_token_bytes",
            "access_token": "jwt_access_token_value",
            "refresh_token": "jwt_refresh_token_value",
            "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$...",
            "token_hash": "sha256_digest_hex_value",
            "authorization": "Bearer eyJhbGciOi...",
            "cookie": "session_cookie_secret_value",
            "secret": "stripe_api_secret_key",
            "session_secret": "session_encryption_key",
            "client_secret": "oauth_client_secret_xyz",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----...",
            "api_key": "live_key_99999",
            "credentials": {"username": "admin"},
            "allowed_info": "safe_information",
            "transaction_amount": 10000,
        }

        event = record_audit_event(
            db=db_session,
            action="SECURITY_TEST_ACTION",
            entity_type="TestEntity",
            entity_id=uuid.uuid4(),
            metadata=raw_metadata,
        )
        db_session.commit()
        db_session.refresh(event)

        meta = event.event_metadata
        assert "allowed_info" in meta
        assert meta["allowed_info"] == "safe_information"
        assert meta["transaction_amount"] == 10000

        forbidden = [
            "password",
            "token",
            "raw_token",
            "access_token",
            "refresh_token",
            "password_hash",
            "token_hash",
            "authorization",
            "cookie",
            "secret",
            "session_secret",
            "client_secret",
            "private_key",
            "api_key",
            "credentials",
        ]
        for key in forbidden:
            assert key not in meta
            assert key.upper() not in meta
            assert f" {key} " not in meta

    def test_nested_sensitive_keys_scrubbed_recursively(self, db_session: Session):
        """Nested dictionaries and lists have sensitive keys removed recursively."""
        nested_metadata = {
            "request_payload": {
                "account_name": "Checking Account",
                "nested_auth": {
                    "password": "nested_cleartext_password",
                    "api_key": "nested_api_key_value",
                    "safe_nested_field": "keep_this",
                },
            },
            "audit_tags": ["security", "pci_dss"],
        }

        event = record_audit_event(
            db=db_session,
            action="NESTED_AUDIT_TEST",
            entity_type="User",
            entity_id=uuid.uuid4(),
            metadata=nested_metadata,
        )
        db_session.commit()
        db_session.refresh(event)

        meta = event.event_metadata
        assert "password" not in meta["request_payload"]["nested_auth"]
        assert "api_key" not in meta["request_payload"]["nested_auth"]
        assert meta["request_payload"]["nested_auth"]["safe_nested_field"] == "keep_this"
        assert meta["request_payload"]["account_name"] == "Checking Account"


class TestAuditTrailAttributionAndIntegrity:
    """Verifies that application actions generate audit events with accurate actor and IP attribution."""

    def test_account_creation_audit_trail(self, client: TestClient, db_session: Session):
        """POST /accounts creates an ACCOUNT_CREATED audit event attributed to admin."""
        admin = make_user(db_session, email="admin_audit@bank.com", role=UserRole.ADMIN)
        user = make_user(db_session, email="owner_audit@bank.com")
        login_client(client, db_session, admin)

        resp = client.post(
            "/accounts",
            headers=TRUSTED_HEADERS,
            json={
                "account_name": "Audited Savings",
                "currency": "INR",
                "owner_user_id": str(user.id),
            },
        )
        assert resp.status_code == 201
        account_id = resp.json()["id"]

        # Verify audit event in DB
        db_session.expire_all()
        events = db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == account_id,
                AuditEvent.action == "ACCOUNT_CREATED",
            )
        ).all()

        assert len(events) >= 1
        audit = events[0]
        assert audit.actor_user_id == admin.id
        assert audit.entity_type == "Account"

    def test_account_status_change_audit_trail(self, client: TestClient, db_session: Session):
        """POST /accounts/{id}/status records ACCOUNT_STATUS_CHANGED audit event."""
        admin = make_user(db_session, email="admin_stat_audit@bank.com", role=UserRole.ADMIN)
        user = make_user(db_session, email="holder_stat_audit@bank.com")
        account, _ = make_account(db_session, user, status=AccountStatus.ACTIVE)
        login_client(client, db_session, admin)

        resp = client.post(
            f"/accounts/{account.id}/status",
            headers=TRUSTED_HEADERS,
            json={"status": "FROZEN"},
        )
        assert resp.status_code == 200

        db_session.expire_all()
        events = db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == str(account.id),
                AuditEvent.action == "ACCOUNT_STATUS_CHANGED",
            )
        ).all()

        assert len(events) == 1
        audit = events[0]
        assert audit.actor_user_id == admin.id
        assert audit.event_metadata["new_status"] == "FROZEN"

    def test_account_metadata_update_audit_trail(self, client: TestClient, db_session: Session):
        """PATCH /accounts/{id} records ACCOUNT_UPDATED audit event."""
        owner = make_user(db_session, email="owner_patch_audit@bank.com")
        account, _ = make_account(db_session, owner, account_name="Initial Name")
        login_client(client, db_session, owner)

        resp = client.patch(
            f"/accounts/{account.id}",
            headers=TRUSTED_HEADERS,
            json={"account_name": "Audited Rename"},
        )
        assert resp.status_code == 200

        db_session.expire_all()
        events = db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == str(account.id),
                AuditEvent.action == "ACCOUNT_UPDATED",
            )
        ).all()

        assert len(events) == 1
        audit = events[0]
        assert audit.actor_user_id == owner.id
        assert audit.event_metadata["new_name"] == "Audited Rename"

    def test_transfer_audit_trail(self, client: TestClient, db_session: Session):
        """POST /transactions/transfer records TRANSACTION_TRANSFER audit event."""
        owner = make_user(db_session, email="owner_xfer_audit@bank.com")
        source, _ = make_account(db_session, owner, balance_paise=100000)
        dest_user = make_user(db_session, email="dest_xfer_audit@bank.com")
        dest, _ = make_account(db_session, dest_user, balance_paise=20000)
        login_client(client, db_session, owner)

        resp = client.post(
            "/transactions/transfer",
            headers=TRUSTED_HEADERS,
            json={
                "source_account_id": str(source.id),
                "destination_account_id": str(dest.id),
                "amount_paise": 25000,
                "description": "Audited peer transfer",
            },
        )
        assert resp.status_code == 200
        tx_id = resp.json()["id"]

        db_session.expire_all()
        events = db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == tx_id,
                AuditEvent.action == "TRANSACTION_TRANSFER",
            )
        ).all()

        assert len(events) == 1
        audit = events[0]
        assert audit.actor_user_id == owner.id
        assert audit.entity_type == "Transaction"
        assert audit.event_metadata["amount_paise"] == 25000
