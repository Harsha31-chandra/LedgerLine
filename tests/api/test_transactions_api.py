"""
End-to-end integration and API tests for LedgerLine financial transaction endpoints.

Covers:
- POST /transactions/deposit: Deposits, balanced entries, validation, CSRF requirement.
- POST /transactions/withdraw: Withdrawals, insufficient funds enforcement.
- POST /transactions/transfer: Transfers, same-account rejection, money conservation.
- Idempotency-Key header exact replay (no double money movement).
- Idempotency-Key collision rejection (HTTP 409).
- GET /accounts/{account_id}/statement: Full chronological statements.
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
from backend.app.schemas import MAX_PAISE_AMOUNT
from backend.app.schemas.transaction import DepositRequest
from backend.app.services.account_service import get_or_create_system_clearing_account
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


def _setup_account(
    db: Session,
    user: User,
    account_number: str,
    balance: int = 0,
    membership_role: MembershipRole = MembershipRole.OWNER,
    status: AccountStatus = AccountStatus.ACTIVE,
) -> Account:
    acc = Account(
        account_number=account_number,
        account_name=f"Acc {account_number}",
        currency="INR",
        balance=balance,
        status=status.value,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)

    mem = AccountMembership(
        user_id=user.id,
        account_id=acc.id,
        membership_role=membership_role.value,
    )
    db.add(mem)
    db.commit()
    return acc


# ===========================================================================
# 1. DEPOSIT ENDPOINT TESTS
# ===========================================================================


def test_api_deposit_success(client: TestClient, db_session: Session):
    """Verify POST /transactions/deposit succeeds and updates balance."""
    user = register_user(db_session, "dep_api@example.com", "Password123!", "Dep API")
    acc = _setup_account(db_session, user, "LL-DEP-001", balance=1000)
    _login(client, db_session, user)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "api-dep-key-1"}
    payload = {"account_id": str(acc.id), "amount_paise": 5000, "description": "API Deposit"}
    response = client.post("/transactions/deposit", json=payload, headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "POSTED"
    assert data["amount_paise"] == 5000
    assert len(data["ledger_entries"]) == 2

    # Verify balance updated in DB
    db_session.refresh(acc)
    assert acc.balance == 6000


def test_api_deposit_invalid_amount_rejected(client: TestClient, db_session: Session):
    """Verify zero and negative amounts return HTTP 422 (Pydantic gt=0)."""
    user = register_user(db_session, "dep_bad@example.com", "Password123!", "Dep Bad")
    acc = _setup_account(db_session, user, "LL-DEP-BAD", balance=0)
    _login(client, db_session, user)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "api-dep-key-bad"}
    r_zero = client.post("/transactions/deposit", json={"account_id": str(acc.id), "amount_paise": 0}, headers=headers)
    assert r_zero.status_code == 422

    r_neg = client.post("/transactions/deposit", json={"account_id": str(acc.id), "amount_paise": -500}, headers=headers)
    assert r_neg.status_code == 422


# ===========================================================================
# 2. WITHDRAWAL ENDPOINT TESTS
# ===========================================================================


def test_api_withdraw_success(client: TestClient, db_session: Session):
    """Verify POST /transactions/withdraw succeeds and updates balance."""
    user = register_user(db_session, "wth_api@example.com", "Password123!", "Wth API")
    acc = _setup_account(db_session, user, "LL-WTH-001", balance=10000)
    _login(client, db_session, user)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "api-wth-key-1"}
    payload = {"account_id": str(acc.id), "amount_paise": 4000}
    response = client.post("/transactions/withdraw", json=payload, headers=headers)

    assert response.status_code == 200
    db_session.refresh(acc)
    assert acc.balance == 6000


def test_api_withdraw_insufficient_funds_rejected(client: TestClient, db_session: Session):
    """Verify withdrawal with insufficient balance returns HTTP 400."""
    user = register_user(db_session, "wth_poor_api@example.com", "Password123!", "Wth Poor")
    acc = _setup_account(db_session, user, "LL-WTH-POOR", balance=1500)
    _login(client, db_session, user)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "api-wth-poor-1"}
    payload = {"account_id": str(acc.id), "amount_paise": 5000}
    response = client.post("/transactions/withdraw", json=payload, headers=headers)

    assert response.status_code == 400
    assert "insufficient balance" in response.json()["detail"].lower() or "insufficient funds" in response.json()["detail"].lower()
    db_session.refresh(acc)
    assert acc.balance == 1500  # Untouched


# ===========================================================================
# 3. TRANSFER ENDPOINT TESTS
# ===========================================================================


def test_api_transfer_success(client: TestClient, db_session: Session):
    """Verify POST /transactions/transfer transfers money between accounts."""
    alice = register_user(db_session, "alice_api@example.com", "Password123!", "Alice")
    bob = register_user(db_session, "bob_api@example.com", "Password123!", "Bob")

    acc_alice = _setup_account(db_session, alice, "LL-ALICE-API", balance=20000)
    acc_bob = _setup_account(db_session, bob, "LL-BOB-API", balance=5000)

    _login(client, db_session, alice)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "api-trf-key-1"}
    payload = {
        "source_account_id": str(acc_alice.id),
        "destination_account_id": str(acc_bob.id),
        "amount_paise": 8000,
        "description": "API Peer Transfer",
    }
    response = client.post("/transactions/transfer", json=payload, headers=headers)

    assert response.status_code == 200
    db_session.refresh(acc_alice)
    db_session.refresh(acc_bob)
    assert acc_alice.balance == 12000
    assert acc_bob.balance == 13000


def test_api_transfer_same_account_rejected(client: TestClient, db_session: Session):
    """Verify transfer to same account returns HTTP 400."""
    user = register_user(db_session, "self_api@example.com", "Password123!", "Self")
    acc = _setup_account(db_session, user, "LL-SELF-API", balance=5000)
    _login(client, db_session, user)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "api-self-trf"}
    payload = {
        "source_account_id": str(acc.id),
        "destination_account_id": str(acc.id),
        "amount_paise": 1000,
    }
    response = client.post("/transactions/transfer", json=payload, headers=headers)

    assert response.status_code == 400
    assert "same account" in response.json()["detail"].lower()


# ===========================================================================
# 4. IDEMPOTENCY ENDPOINT TESTS
# ===========================================================================


def test_api_idempotency_exact_replay(client: TestClient, db_session: Session):
    """Verify repeated HTTP call with same key returns identical response without moving money again."""
    user = register_user(db_session, "idemp_api@example.com", "Password123!", "Idemp API")
    acc = _setup_account(db_session, user, "LL-IDEMP-01", balance=10000)
    _login(client, db_session, user)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "unique-idemp-123"}
    payload = {"account_id": str(acc.id), "amount_paise": 3000}

    # First request
    r1 = client.post("/transactions/deposit", json=payload, headers=headers)
    assert r1.status_code == 200

    db_session.refresh(acc)
    assert acc.balance == 13000

    # Second identical request
    r2 = client.post("/transactions/deposit", json=payload, headers=headers)
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]

    # Balance must remain 13000 (not 16000)
    db_session.refresh(acc)
    assert acc.balance == 13000


def test_api_idempotency_conflict_rejected(client: TestClient, db_session: Session):
    """Verify reusing idempotency key with altered payload returns HTTP 409 Conflict."""
    user = register_user(db_session, "conflict_api@example.com", "Password123!", "Conflict API")
    acc = _setup_account(db_session, user, "LL-CONFLICT-01", balance=10000)
    _login(client, db_session, user)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "conflict-idemp-999"}

    # First request: 2000
    r1 = client.post("/transactions/deposit", json={"account_id": str(acc.id), "amount_paise": 2000}, headers=headers)
    assert r1.status_code == 200

    # Second request with SAME key but amount: 5000
    r2 = client.post("/transactions/deposit", json={"account_id": str(acc.id), "amount_paise": 5000}, headers=headers)
    assert r2.status_code == 409
    assert "previously used with different parameters" in r2.json()["detail"].lower()


# ===========================================================================
# 5. STATEMENT ENDPOINT TESTS
# ===========================================================================


def test_api_account_statement(client: TestClient, db_session: Session):
    """Verify GET /accounts/{id}/statement returns full chronological transaction history."""
    user = register_user(db_session, "stmt_api@example.com", "Password123!", "Stmt API")
    acc = _setup_account(db_session, user, "LL-STMT-API", balance=0)
    _login(client, db_session, user)

    # 1. Deposit 10000
    client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": 10000},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "stmt-dep"},
    )
    # 2. Withdraw 2500
    client.post(
        "/transactions/withdraw",
        json={"account_id": str(acc.id), "amount_paise": 2500},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "stmt-wth"},
    )

    response = client.get(f"/accounts/{acc.id}/statement")
    assert response.status_code == 200
    data = response.json()
    assert data["account_number"] == "LL-STMT-API"
    assert data["balance_paise"] == 7500
    assert len(data["entries"]) == 2
    assert data["entries"][0]["transaction_type"] == "DEPOSIT"
    assert data["entries"][0]["amount_paise"] == 10000
    assert data["entries"][1]["transaction_type"] == "WITHDRAWAL"
    assert data["entries"][1]["amount_paise"] == 2500


# ===========================================================================
# 6. GET /transactions/{id} AUTHORIZATION TESTS (SEC-001, AUTH-001)
# ===========================================================================


def test_api_get_transaction_authorized_member_success(client: TestClient, db_session: Session):
    """Verify authorized account member can retrieve transaction details."""
    user = register_user(db_session, "tx_auth@example.com", "Password123!", "Tx Auth")
    acc = _setup_account(db_session, user, "LL-TX-AUTH", balance=5000)
    _login(client, db_session, user)

    # Make a deposit to generate a transaction
    dep_res = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": 2000},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "tx-get-dep-1"},
    )
    assert dep_res.status_code == 200
    tx_id = dep_res.json()["id"]

    response = client.get(f"/transactions/{tx_id}")
    assert response.status_code == 200
    assert response.json()["id"] == tx_id
    assert response.json()["amount_paise"] == 2000


def test_api_get_transaction_non_member_returns_404(client: TestClient, db_session: Session):
    """Verify non-member HOLDER receives HTTP 404 (IDOR defense)."""
    alice = register_user(db_session, "tx_alice@example.com", "Password123!", "Tx Alice")
    bob = register_user(db_session, "tx_bob@example.com", "Password123!", "Tx Bob")
    acc = _setup_account(db_session, alice, "LL-TX-ALICE", balance=5000)

    # Alice deposits
    _login(client, db_session, alice)
    dep_res = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": 2000},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "tx-get-dep-2"},
    )
    tx_id = dep_res.json()["id"]

    # Bob attempts to retrieve Alice's transaction
    _login(client, db_session, bob)
    response = client.get(f"/transactions/{tx_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Transaction not found"}


def test_api_get_transaction_admin_without_membership_returns_404(client: TestClient, db_session: Session):
    """Verify ADMIN without account membership receives HTTP 404 (AUTH-001)."""
    alice = register_user(db_session, "tx_cust@example.com", "Password123!", "Tx Cust")
    admin = register_user(db_session, "tx_admin@example.com", "Password123!", "Tx Admin")
    admin.role = UserRole.ADMIN.value
    db_session.commit()

    acc = _setup_account(db_session, alice, "LL-TX-CUST", balance=5000)

    _login(client, db_session, alice)
    dep_res = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": 2000},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "tx-get-dep-3"},
    )
    tx_id = dep_res.json()["id"]

    # Admin without membership requests transaction
    _login(client, db_session, admin)
    response = client.get(f"/transactions/{tx_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Transaction not found"}


def test_api_get_transaction_auditor_without_membership_returns_404(client: TestClient, db_session: Session):
    """Verify AUDITOR without account membership receives HTTP 404 (AUTH-001)."""
    alice = register_user(db_session, "tx_cust2@example.com", "Password123!", "Tx Cust2")
    auditor = register_user(db_session, "tx_auditor@example.com", "Password123!", "Tx Auditor")
    auditor.role = UserRole.AUDITOR.value
    db_session.commit()

    acc = _setup_account(db_session, alice, "LL-TX-CUST2", balance=5000)

    _login(client, db_session, alice)
    dep_res = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": 2000},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "tx-get-dep-4"},
    )
    tx_id = dep_res.json()["id"]

    # Auditor without membership requests transaction
    _login(client, db_session, auditor)
    response = client.get(f"/transactions/{tx_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Transaction not found"}


def test_api_get_transaction_inactive_user_returns_403(client: TestClient, db_session: Session):
    """Verify inactive user receives HTTP 403 when retrieving transaction."""
    user = register_user(db_session, "tx_inact@example.com", "Password123!", "Tx Inact")
    acc = _setup_account(db_session, user, "LL-TX-INACT", balance=5000)
    _login(client, db_session, user)

    dep_res = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": 2000},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "tx-get-dep-5"},
    )
    tx_id = dep_res.json()["id"]

    # Deactivate user
    user.is_active = False
    db_session.commit()

    response = client.get(f"/transactions/{tx_id}")
    assert response.status_code == 403
    assert "inactive" in response.json()["detail"].lower()


def test_api_get_transaction_string_role_regression(client: TestClient, db_session: Session):
    """Verify user with raw string role in DB does not crash get_transaction_by_id (SEC-001)."""
    user = register_user(db_session, "tx_str_role@example.com", "Password123!", "Tx Str Role")
    user.role = "HOLDER"  # raw string as stored in DB
    db_session.commit()

    acc = _setup_account(db_session, user, "LL-TX-STR-ROLE", balance=5000)
    _login(client, db_session, user)

    dep_res = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": 1500},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "tx-get-str-role-1"},
    )
    tx_id = dep_res.json()["id"]

    response = client.get(f"/transactions/{tx_id}")
    assert response.status_code == 200
    assert response.json()["id"] == tx_id


# ===========================================================================
# 7. CLEARING ACCOUNT TRANSFER PROHIBITION TESTS (FIN-002)
# ===========================================================================


def test_api_transfer_to_clearing_account_rejected(client: TestClient, db_session: Session):
    """Verify transfer targeting SYSTEM_CLEARING returns HTTP 400 (FIN-002)."""
    user = register_user(db_session, "trf_clearing@example.com", "Password123!", "Trf Clearing")
    acc = _setup_account(db_session, user, "LL-TRF-CL-01", balance=10000)
    clearing = get_or_create_system_clearing_account(db_session)
    _login(client, db_session, user)

    headers = {**TRUSTED_HEADERS, "Idempotency-Key": "trf-clearing-dest"}
    payload = {
        "source_account_id": str(acc.id),
        "destination_account_id": str(clearing.id),
        "amount_paise": 2000,
    }
    response = client.post("/transactions/transfer", json=payload, headers=headers)
    assert response.status_code == 400
    assert "system clearing account cannot be targeted by peer-to-peer transfers" in response.json()["detail"].lower()


# ===========================================================================
# 8. STRICT MONETARY VALIDATION TESTS (VAL-001, VAL-002)
# ===========================================================================


def test_api_strict_amount_types_rejected(client: TestClient, db_session: Session):
    """Verify boolean, float, and string amounts return HTTP 422 (VAL-001)."""
    user = register_user(db_session, "val_strict@example.com", "Password123!", "Val Strict")
    acc = _setup_account(db_session, user, "LL-VAL-STRICT", balance=50000)
    _login(client, db_session, user)

    # 1. Booleans (True / False)
    r_bool_true = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": True},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "strict-bool-1"},
    )
    assert r_bool_true.status_code == 422

    r_bool_false = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": False},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "strict-bool-2"},
    )
    assert r_bool_false.status_code == 422

    # 2. Floats
    r_float = client.post(
        "/transactions/withdraw",
        json={"account_id": str(acc.id), "amount_paise": 100.50},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "strict-float-1"},
    )
    assert r_float.status_code == 422

    # 3. Numeric string
    r_str = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": "5000"},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "strict-str-1"},
    )
    assert r_str.status_code == 422


def test_api_amount_bounds_rejected(client: TestClient, db_session: Session):
    """Verify amounts exceeding signed 64-bit BigInt max return HTTP 422 (VAL-002)."""
    user = register_user(db_session, "val_bounds@example.com", "Password123!", "Val Bounds")
    acc = _setup_account(db_session, user, "LL-VAL-BOUNDS", balance=10000)
    _login(client, db_session, user)

    overflow_amount = MAX_PAISE_AMOUNT + 1  # 9_223_372_036_854_775_808

    # Deposit with overflow returns 422
    r_dep = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": overflow_amount},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "overflow-dep"},
    )
    assert r_dep.status_code == 422

    # Withdrawal with overflow returns 422
    r_wth = client.post(
        "/transactions/withdraw",
        json={"account_id": str(acc.id), "amount_paise": overflow_amount},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "overflow-wth"},
    )
    assert r_wth.status_code == 422

    # Maximum allowed integer validates schema without Pydantic ValidationError
    valid_req = DepositRequest(account_id=acc.id, amount_paise=MAX_PAISE_AMOUNT)
    assert valid_req.amount_paise == MAX_PAISE_AMOUNT

    # Large valid integer succeeds via HTTP endpoint
    r_valid = client.post(
        "/transactions/deposit",
        json={"account_id": str(acc.id), "amount_paise": 500_000_000},
        headers={**TRUSTED_HEADERS, "Idempotency-Key": "valid-large-dep"},
    )
    assert r_valid.status_code == 200
    assert r_valid.json()["amount_paise"] == 500_000_000
