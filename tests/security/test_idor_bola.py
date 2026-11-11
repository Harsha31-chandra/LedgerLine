"""
Security Test Suite: Broken Object Level Authorization (BOLA) and IDOR Defense.

Validates:
- Users cannot access, view, or modify accounts owned by other users by altering UUIDs.
- Non-members querying unowned account UUIDs receive HTTP 404 (Anti-Enumeration / Anti-IDOR).
- Users cannot view transactions belonging to accounts where they have no membership.
- Unrelated third parties cannot view peer-to-peer transactions between two other users.
- Mutual counterparties (sender and recipient) can both view their shared transaction.
- All rejected attempts preserve database state without modifying balances or creating entries.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.account import Account
from backend.app.models.ledger_entry import LedgerEntry
from backend.app.models.transaction import Transaction
from backend.app.models.user import UserRole
from tests.security.conftest import (
    TRUSTED_HEADERS,
    login_client,
    make_account,
    make_user,
)


def test_idor_prevented_on_get_account_detail(client: TestClient, db_session: Session):
    """User B attempting to read User A's account receives HTTP 404 Anti-IDOR response."""
    user_a = make_user(db_session, email="alice@example.com")
    user_b = make_user(db_session, email="bob@example.com")
    acc_a, _ = make_account(db_session, user_a, account_name="Alice Secret Savings", balance_paise=50000)

    # Bob logs in and queries Alice's account UUID
    login_client(client, db_session, user_b)
    response = client.get(f"/accounts/{acc_a.id}")

    # Must return 404 Not Found to prevent existence enumeration
    assert response.status_code == 404
    assert response.json()["detail"] == "Account not found"


def test_idor_prevented_on_patch_account_metadata(client: TestClient, db_session: Session):
    """User B attempting to rename User A's account receives HTTP 404 and leaves DB unchanged."""
    user_a = make_user(db_session, email="alice_patch@example.com")
    user_b = make_user(db_session, email="bob_patch@example.com")
    acc_a, _ = make_account(db_session, user_a, account_name="Original Name")

    login_client(client, db_session, user_b)
    response = client.patch(
        f"/accounts/{acc_a.id}",
        json={"account_name": "Hacked Name by Bob"},
        headers=TRUSTED_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Account not found"

    # Verify database state was not modified
    db_session.expire_all()
    reloaded_a = db_session.get(Account, acc_a.id)
    assert reloaded_a.account_name == "Original Name"


def test_idor_prevented_on_get_statement(client: TestClient, db_session: Session):
    """User B attempting to view User A's ledger statement receives HTTP 404."""
    user_a = make_user(db_session, email="alice_stmt@example.com")
    user_b = make_user(db_session, email="bob_stmt@example.com")
    acc_a, _ = make_account(db_session, user_a, account_name="Alice Stmt Account")

    login_client(client, db_session, user_b)
    response = client.get(f"/accounts/{acc_a.id}/statement")

    assert response.status_code == 404
    assert response.json()["detail"] == "Account not found"


def test_idor_prevented_on_deposit_to_unowned_account(client: TestClient, db_session: Session):
    """User B attempting to initiate a deposit to User A's account is rejected with HTTP 404."""
    user_a = make_user(db_session, email="alice_dep@example.com")
    user_b = make_user(db_session, email="bob_dep@example.com")
    acc_a, _ = make_account(db_session, user_a, balance_paise=10000)

    pre_balance = acc_a.balance
    pre_tx_count = len(db_session.scalars(select(Transaction)).all())

    login_client(client, db_session, user_b)
    response = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc_a.id), "amount_paise": 5000, "description": "Unauthorized deposit"},
        headers=TRUSTED_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Account not found"

    # Verify no money movement occurred in database
    db_session.expire_all()
    assert db_session.get(Account, acc_a.id).balance == pre_balance
    assert len(db_session.scalars(select(Transaction)).all()) == pre_tx_count


def test_idor_prevented_on_withdraw_from_unowned_account(client: TestClient, db_session: Session):
    """User B attempting to withdraw funds from User A's account is rejected with HTTP 404."""
    user_a = make_user(db_session, email="alice_wd@example.com")
    user_b = make_user(db_session, email="bob_wd@example.com")
    acc_a, _ = make_account(db_session, user_a, balance_paise=100000)

    pre_balance = acc_a.balance
    pre_tx_count = len(db_session.scalars(select(Transaction)).all())
    pre_entry_count = len(db_session.scalars(select(LedgerEntry)).all())

    login_client(client, db_session, user_b)
    response = client.post(
        "/transactions/withdraw",
        json={"account_id": str(acc_a.id), "amount_paise": 20000, "description": "Theft attempt"},
        headers=TRUSTED_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Account not found"

    # Verify absolute state immutability
    db_session.expire_all()
    assert db_session.get(Account, acc_a.id).balance == pre_balance
    assert len(db_session.scalars(select(Transaction)).all()) == pre_tx_count
    assert len(db_session.scalars(select(LedgerEntry)).all()) == pre_entry_count


def test_idor_prevented_on_transfer_from_unowned_source_account(client: TestClient, db_session: Session):
    """User B attempting to transfer funds from User A's account to User B's account is rejected with HTTP 404."""
    user_a = make_user(db_session, email="alice_tr@example.com")
    user_b = make_user(db_session, email="bob_tr@example.com")
    acc_a, _ = make_account(db_session, user_a, balance_paise=100000)
    acc_b, _ = make_account(db_session, user_b, balance_paise=0)

    pre_balance_a = acc_a.balance
    pre_balance_b = acc_b.balance

    login_client(client, db_session, user_b)
    response = client.post(
        "/transactions/transfer",
        json={
            "source_account_id": str(acc_a.id),
            "destination_account_id": str(acc_b.id),
            "amount_paise": 30000,
            "description": "Unauthorized transfer",
        },
        headers=TRUSTED_HEADERS,
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    # Verify neither account was debited or credited
    db_session.expire_all()
    assert db_session.get(Account, acc_a.id).balance == pre_balance_a
    assert db_session.get(Account, acc_b.id).balance == pre_balance_b


def test_idor_prevented_on_get_transaction_by_unrelated_user(client: TestClient, db_session: Session):
    """User B cannot view details of a transaction executed by User A on User A's account."""
    user_a = make_user(db_session, email="alice_tx@example.com")
    user_b = make_user(db_session, email="bob_tx@example.com")
    acc_a, _ = make_account(db_session, user_a, balance_paise=50000)

    # Alice performs a valid deposit
    login_client(client, db_session, user_a)
    dep_res = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc_a.id), "amount_paise": 10000, "description": "Alice Deposit"},
        headers=TRUSTED_HEADERS,
    )
    assert dep_res.status_code == 200
    tx_id = dep_res.json()["id"]

    # Bob attempts to view Alice's transaction by ID
    login_client(client, db_session, user_b)
    response = client.get(f"/transactions/{tx_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Transaction not found"


def test_idor_prevented_on_peer_transfer_for_third_party(client: TestClient, db_session: Session):
    """A third party (Charlie) cannot inspect a transaction between Alice and Bob."""
    alice = make_user(db_session, email="alice_p2p@example.com")
    bob = make_user(db_session, email="bob_p2p@example.com")
    charlie = make_user(db_session, email="charlie_p2p@example.com")

    acc_alice, _ = make_account(db_session, alice, balance_paise=100000)
    acc_bob, _ = make_account(db_session, bob, balance_paise=10000)

    # Alice transfers funds to Bob
    login_client(client, db_session, alice)
    tr_res = client.post(
        "/transactions/transfer",
        json={
            "source_account_id": str(acc_alice.id),
            "destination_account_id": str(acc_bob.id),
            "amount_paise": 25000,
            "description": "Alice to Bob Transfer",
        },
        headers=TRUSTED_HEADERS,
    )
    assert tr_res.status_code == 200
    tx_id = tr_res.json()["id"]

    # Alice (sender) can inspect transaction
    login_client(client, db_session, alice)
    assert client.get(f"/transactions/{tx_id}").status_code == 200

    # Bob (recipient) can inspect transaction
    login_client(client, db_session, bob)
    assert client.get(f"/transactions/{tx_id}").status_code == 200

    # Charlie (unrelated third party) receives 404 Anti-IDOR
    login_client(client, db_session, charlie)
    response_charlie = client.get(f"/transactions/{tx_id}")
    assert response_charlie.status_code == 404
    assert response_charlie.json()["detail"] == "Transaction not found"


def test_idor_prevented_on_nonexistent_vs_unowned_uuid_indistinguishability(client: TestClient, db_session: Session):
    """Verify that an unowned account UUID and a completely nonexistent UUID return identical 404 responses."""
    user_a = make_user(db_session, email="alice_timing@example.com")
    user_b = make_user(db_session, email="bob_timing@example.com")
    acc_a, _ = make_account(db_session, user_a)
    random_uuid = str(uuid.uuid4())

    login_client(client, db_session, user_b)

    # Response for Alice's account (exists, but Bob is not a member)
    res_unowned = client.get(f"/accounts/{acc_a.id}")
    # Response for completely non-existent account
    res_nonexistent = client.get(f"/accounts/{random_uuid}")

    assert res_unowned.status_code == 404
    assert res_nonexistent.status_code == 404
    assert res_unowned.json() == res_nonexistent.json() == {"detail": "Account not found"}
