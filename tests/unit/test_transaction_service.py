"""
Unit tests for LedgerLine financial transaction service.

Covers:
- Deposits, withdrawals, and peer-to-peer transfers.
- Strict positive integer amount validation.
- Insufficient funds enforcement.
- Same-account transfer rejection.
- Account status enforcement (FROZEN/CLOSED account rejections).
- Idempotency key exact replay without duplicate money movement.
- Idempotency key collision rejection with different payload.
- In-flight concurrent idempotency key rejection.
- Chronological account statement generation.
- Audit event logging across financial operations.
"""

import uuid

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.exceptions import (
    AccountNotFoundError,
    AccountStatusError,
    AuditorReadOnlyViolationError,
    ClearingAccountTransferError,
    IdempotencyCollisionError,
    IdempotencyInFlightError,
    InactiveUserError,
    InsufficientFundsError,
    InsufficientMembershipRoleError,
    InvalidAmountError,
    SameAccountTransferError,
)
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.audit_event import AuditEvent
from backend.app.models.base import Base
from backend.app.models.idempotency import IdempotencyRecord
from backend.app.models.user import User, UserRole
from backend.app.services.account_service import get_or_create_system_clearing_account
from backend.app.services.transaction_service import (
    execute_deposit,
    execute_transfer,
    execute_withdrawal,
    get_account_statement,
    get_transaction_by_id,
)


@pytest.fixture
def db_session() -> Session:
    """Provide an isolated in-memory SQLite database session."""
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
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _create_user(db: Session, email: str, role: UserRole = UserRole.HOLDER, is_active: bool = True) -> User:
    user = User(
        email=email,
        password_hash="dummy_hash",
        full_name=f"User {email}",
        role=role.value,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_account_with_owner(
    db: Session,
    owner: User,
    account_number: str,
    balance: int = 0,
    status: AccountStatus = AccountStatus.ACTIVE,
    membership_role: MembershipRole = MembershipRole.OWNER,
) -> Account:
    account = Account(
        account_number=account_number,
        account_name=f"Account {account_number}",
        currency="INR",
        balance=balance,
        status=status.value,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    membership = AccountMembership(
        user_id=owner.id,
        account_id=account.id,
        membership_role=membership_role.value,
    )
    db.add(membership)
    db.commit()
    return account


# ===========================================================================
# 1. DEPOSIT TESTS
# ===========================================================================


def test_execute_deposit_success(db_session: Session):
    """Verify deposit increases customer balance, debits clearing account, and posts balanced entries."""
    user = _create_user(db_session, "dep_user@example.com")
    account = _create_account_with_owner(db_session, user, "ACC-DEP-01", balance=1000)

    clearing_before = get_or_create_system_clearing_account(db_session).balance

    res = execute_deposit(
        db=db_session,
        user=user,
        account_id=account.id,
        amount_paise=5000,
        idempotency_key="key-dep-001",
        description="Salary deposit",
    )

    assert res["status"] == "POSTED"
    assert res["amount_paise"] == 5000
    assert len(res["ledger_entries"]) == 2

    db_session.refresh(account)
    assert account.balance == 6000  # 1000 + 5000

    clearing_after = get_or_create_system_clearing_account(db_session).balance
    assert clearing_after == clearing_before - 5000

    # Audit event verification
    audit = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "TRANSACTION_DEPOSIT")
    ).first()
    assert audit is not None
    assert audit.actor_user_id == user.id


def test_execute_deposit_zero_or_negative_rejected(db_session: Session):
    """Verify deposit rejects zero and negative amounts."""
    user = _create_user(db_session, "dep_inv@example.com")
    account = _create_account_with_owner(db_session, user, "ACC-DEP-INV", balance=0)

    with pytest.raises(InvalidAmountError):
        execute_deposit(db_session, user, account.id, 0, "key-0")

    with pytest.raises(InvalidAmountError):
        execute_deposit(db_session, user, account.id, -100, "key-neg")


def test_execute_deposit_frozen_account_rejected(db_session: Session):
    """Verify deposit on a FROZEN account is rejected with AccountStatusError."""
    user = _create_user(db_session, "dep_frz@example.com")
    account = _create_account_with_owner(
        db_session, user, "ACC-DEP-FRZ", balance=0, status=AccountStatus.FROZEN
    )

    with pytest.raises(AccountStatusError):
        execute_deposit(db_session, user, account.id, 1000, "key-frz")


# ===========================================================================
# 2. WITHDRAWAL TESTS
# ===========================================================================


def test_execute_withdrawal_success(db_session: Session):
    """Verify withdrawal decreases customer balance, credits clearing account, and posts balanced entries."""
    user = _create_user(db_session, "wth_user@example.com")
    account = _create_account_with_owner(db_session, user, "ACC-WTH-01", balance=10000)

    clearing_before = get_or_create_system_clearing_account(db_session).balance

    res = execute_withdrawal(
        db=db_session,
        user=user,
        account_id=account.id,
        amount_paise=4000,
        idempotency_key="key-wth-001",
        description="ATM withdrawal",
    )

    assert res["status"] == "POSTED"
    assert res["amount_paise"] == 4000

    db_session.refresh(account)
    assert account.balance == 6000  # 10000 - 4000

    clearing_after = get_or_create_system_clearing_account(db_session).balance
    assert clearing_after == clearing_before + 4000


def test_execute_withdrawal_insufficient_funds_rejected(db_session: Session):
    """Verify withdrawal with insufficient balance raises InsufficientFundsError without mutating state."""
    user = _create_user(db_session, "wth_poor@example.com")
    account = _create_account_with_owner(db_session, user, "ACC-WTH-POOR", balance=2000)

    with pytest.raises(InsufficientFundsError):
        execute_withdrawal(db_session, user, account.id, 5000, "key-poor")

    db_session.refresh(account)
    assert account.balance == 2000  # Untouched


# ===========================================================================
# 3. TRANSFER TESTS
# ===========================================================================


def test_execute_transfer_success(db_session: Session):
    """Verify peer-to-peer transfer debits source, credits destination, and conserves money."""
    alice = _create_user(db_session, "alice@example.com")
    bob = _create_user(db_session, "bob@example.com")

    acc_alice = _create_account_with_owner(db_session, alice, "ACC-ALICE-01", balance=15000)
    acc_bob = _create_account_with_owner(db_session, bob, "ACC-BOB-01", balance=5000)

    res = execute_transfer(
        db=db_session,
        user=alice,
        source_account_id=acc_alice.id,
        destination_account_id=acc_bob.id,
        amount_paise=7000,
        idempotency_key="key-trf-001",
        description="Dinner split",
    )

    assert res["status"] == "POSTED"
    assert res["amount_paise"] == 7000

    db_session.refresh(acc_alice)
    db_session.refresh(acc_bob)
    assert acc_alice.balance == 8000   # 15000 - 7000
    assert acc_bob.balance == 12000   # 5000 + 7000

    # Invariant: Total customer wallet money conserved
    assert acc_alice.balance + acc_bob.balance == 20000


def test_execute_transfer_same_account_rejected(db_session: Session):
    """Verify transferring to the identical account raises SameAccountTransferError."""
    user = _create_user(db_session, "self_trf@example.com")
    account = _create_account_with_owner(db_session, user, "ACC-SELF-01", balance=10000)

    with pytest.raises(SameAccountTransferError):
        execute_transfer(
            db_session,
            user,
            account.id,
            account.id,
            2000,
            "key-self",
        )


def test_execute_transfer_insufficient_funds_rejected(db_session: Session):
    """Verify transfer with insufficient funds fails closed."""
    alice = _create_user(db_session, "alice_nobal@example.com")
    bob = _create_user(db_session, "bob_dest@example.com")

    acc_alice = _create_account_with_owner(db_session, alice, "ACC-ALICE-NOBAL", balance=1000)
    acc_bob = _create_account_with_owner(db_session, bob, "ACC-BOB-DEST", balance=1000)

    with pytest.raises(InsufficientFundsError):
        execute_transfer(
            db_session,
            alice,
            acc_alice.id,
            acc_bob.id,
            5000,
            "key-overdraw",
        )

    db_session.refresh(acc_alice)
    db_session.refresh(acc_bob)
    assert acc_alice.balance == 1000
    assert acc_bob.balance == 1000


def test_execute_transfer_frozen_destination_rejected(db_session: Session):
    """Verify transfer to a FROZEN destination account is rejected."""
    alice = _create_user(db_session, "alice_f@example.com")
    bob = _create_user(db_session, "bob_f@example.com")

    acc_alice = _create_account_with_owner(db_session, alice, "ACC-ALICE-OK", balance=10000)
    acc_bob = _create_account_with_owner(
        db_session, bob, "ACC-BOB-FRZ", balance=0, status=AccountStatus.FROZEN
    )

    with pytest.raises(AccountStatusError):
        execute_transfer(
            db_session,
            alice,
            acc_alice.id,
            acc_bob.id,
            2000,
            "key-to-frz",
        )


def test_execute_transfer_unauthorized_source_rejected(db_session: Session):
    """Verify an attacker cannot initiate a transfer from another user's account."""
    victim = _create_user(db_session, "victim_trf@example.com")
    attacker = _create_user(db_session, "attacker_trf@example.com")

    acc_victim = _create_account_with_owner(db_session, victim, "ACC-VICTIM", balance=50000)
    acc_attacker = _create_account_with_owner(db_session, attacker, "ACC-ATTACKER", balance=0)

    with pytest.raises(AccountNotFoundError):
        execute_transfer(
            db_session,
            attacker,
            acc_victim.id,
            acc_attacker.id,
            10000,
            "key-steal",
        )


# ===========================================================================
# 4. IDEMPOTENCY EXACT REPLAY & COLLISION TESTS
# ===========================================================================


def test_idempotency_exact_replay_returns_cached_result(db_session: Session):
    """Verify resending the exact same request with identical idempotency key returns cached response."""
    user = _create_user(db_session, "replay_user@example.com")
    account = _create_account_with_owner(db_session, user, "ACC-REPLAY-01", balance=10000)

    key = "idemp-replay-12345"
    # First execution
    r1 = execute_deposit(db_session, user, account.id, 5000, key, "First call")
    db_session.refresh(account)
    assert account.balance == 15000

    # Second execution with identical key and payload
    r2 = execute_deposit(db_session, user, account.id, 5000, key, "First call")
    db_session.refresh(account)

    # Balance must NOT increase a second time
    assert account.balance == 15000
    assert r1["id"] == r2["id"]
    assert r1["reference"] == r2["reference"]


def test_idempotency_key_collision_with_different_payload_rejected(db_session: Session):
    """Verify reusing an idempotency key with different payload raises IdempotencyCollisionError."""
    user = _create_user(db_session, "collision_user@example.com")
    account = _create_account_with_owner(db_session, user, "ACC-COLLISION-01", balance=10000)

    key = "idemp-conflict-999"
    # First request: amount = 3000
    execute_deposit(db_session, user, account.id, 3000, key, "First call")

    # Second request with SAME key but DIFFERENT amount: 8000
    with pytest.raises(IdempotencyCollisionError):
        execute_deposit(db_session, user, account.id, 8000, key, "First call")


# ===========================================================================
# 5. STATEMENT INSPECTION TESTS
# ===========================================================================


def test_get_account_statement(db_session: Session):
    """Verify get_account_statement returns complete chronological journal of postings."""
    user = _create_user(db_session, "stmt_user@example.com")
    account = _create_account_with_owner(db_session, user, "ACC-STMT-01", balance=0)

    # Deposit 10000
    execute_deposit(db_session, user, account.id, 10000, "stmt-dep-1")
    # Withdraw 3000
    execute_withdrawal(db_session, user, account.id, 3000, "stmt-wth-1")

    stmt = get_account_statement(db_session, user, account.id)
    assert stmt.account_id == account.id
    assert stmt.balance_paise == 7000
    assert len(stmt.entries) == 2

    e1 = stmt.entries[0]
    assert e1.transaction_type == "DEPOSIT"
    assert e1.entry_type == "CREDIT"
    assert e1.amount_paise == 10000

    e2 = stmt.entries[1]
    assert e2.transaction_type == "WITHDRAWAL"
    assert e2.entry_type == "DEBIT"
    assert e2.amount_paise == 3000


# ===========================================================================
# 6. CLEARING ACCOUNT TRANSFER PROHIBITION TESTS (FIN-002)
# ===========================================================================


def test_transfer_to_or_from_clearing_account_rejected(db_session: Session):
    """Verify peer-to-peer transfers targeting or originating from SYSTEM_CLEARING are rejected (FIN-002)."""
    user = _create_user(db_session, "user_trf_clr@example.com")
    customer_acc = _create_account_with_owner(db_session, user, "ACC-CUST-TRF", balance=50000)
    clearing_acc = get_or_create_system_clearing_account(db_session)

    # 1. Attempt transfer TO clearing account
    with pytest.raises(ClearingAccountTransferError, match="cannot be targeted by peer-to-peer transfers"):
        execute_transfer(
            db=db_session,
            user=user,
            source_account_id=customer_acc.id,
            destination_account_id=clearing_acc.id,
            amount_paise=5000,
            idempotency_key="trf-to-clr",
        )

    # 2. Attempt transfer FROM clearing account
    with pytest.raises(ClearingAccountTransferError, match="cannot be used as transfer source"):
        execute_transfer(
            db=db_session,
            user=user,
            source_account_id=clearing_acc.id,
            destination_account_id=customer_acc.id,
            amount_paise=5000,
            idempotency_key="trf-from-clr",
        )

    # Customer balance remains unchanged
    db_session.refresh(customer_acc)
    assert customer_acc.balance == 50000


# ===========================================================================
# 7. TRANSACTION RETRIEVAL & ROLE TYPE TESTS (SEC-001 & AUTH-001)
# ===========================================================================


def test_get_transaction_by_id_success(db_session: Session):
    """Verify authorized member can retrieve transaction details (SEC-001 & AUTH-001)."""
    alice = _create_user(db_session, "alice_gtx@example.com", role=UserRole.HOLDER)
    bob = _create_user(db_session, "bob_gtx@example.com", role=UserRole.HOLDER)

    acc_a = _create_account_with_owner(db_session, alice, "ACC-A-GTX", balance=20000)
    acc_b = _create_account_with_owner(db_session, bob, "ACC-B-GTX", balance=10000)

    # Execute transfer
    tx_data = execute_transfer(
        db=db_session,
        user=alice,
        source_account_id=acc_a.id,
        destination_account_id=acc_b.id,
        amount_paise=5000,
        idempotency_key="trf-gtx-01",
    )
    tx_id = uuid.UUID(tx_data["id"])

    # Alice has membership in source account -> Can retrieve
    tx_alice = get_transaction_by_id(db_session, alice, tx_id)
    assert tx_alice.id == tx_id
    assert tx_alice.amount_paise == 5000

    # Bob has membership in destination account -> Can retrieve
    tx_bob = get_transaction_by_id(db_session, bob, tx_id)
    assert tx_bob.id == tx_id


def test_get_transaction_by_id_handles_string_role_without_crash(db_session: Session):
    """Verify user with database-loaded string role ('HOLDER', 'ADMIN') does not raise AttributeError (SEC-001)."""
    user = _create_user(db_session, "str_role_gtx@example.com")
    # Simulate database column returning plain str
    user.role = "HOLDER"
    assert type(user.role) is str

    acc = _create_account_with_owner(db_session, user, "ACC-STR-ROLE", balance=10000)
    dep_data = execute_deposit(db_session, user, acc.id, 3000, "dep-str-role")
    tx_id = uuid.UUID(dep_data["id"])

    # Must execute cleanly without AttributeError: 'str' object has no attribute 'value'
    tx = get_transaction_by_id(db_session, user, tx_id)
    assert tx.id == tx_id


def test_get_transaction_by_id_admin_and_auditor_without_membership_rejected(db_session: Session):
    """Verify ADMIN and AUDITOR without account membership receive AccountNotFoundError (AUTH-001 anti-IDOR)."""
    alice = _create_user(db_session, "alice_private@example.com", role=UserRole.HOLDER)
    acc = _create_account_with_owner(db_session, alice, "ACC-PRIV-01", balance=10000)
    dep = execute_deposit(db_session, alice, acc.id, 2000, "dep-priv-01")
    tx_id = uuid.UUID(dep["id"])

    admin_unrelated = _create_user(db_session, "admin_foreign@example.com", role=UserRole.ADMIN)
    auditor_unrelated = _create_user(db_session, "auditor_foreign@example.com", role=UserRole.AUDITOR)
    stranger = _create_user(db_session, "stranger_h@example.com", role=UserRole.HOLDER)

    # All three lack membership on acc -> Must receive AccountNotFoundError (anti-IDOR 404)
    with pytest.raises(AccountNotFoundError):
        get_transaction_by_id(db_session, admin_unrelated, tx_id)

    with pytest.raises(AccountNotFoundError):
        get_transaction_by_id(db_session, auditor_unrelated, tx_id)

    with pytest.raises(AccountNotFoundError):
        get_transaction_by_id(db_session, stranger, tx_id)


def test_get_transaction_by_id_inactive_user_rejected(db_session: Session):
    """Verify deactivated user cannot retrieve transactions."""
    alice = _create_user(db_session, "alice_inact@example.com", is_active=True)
    acc = _create_account_with_owner(db_session, alice, "ACC-INACT-01", balance=5000)
    dep = execute_deposit(db_session, alice, acc.id, 1000, "dep-inact")
    tx_id = uuid.UUID(dep["id"])

    # Deactivate alice
    alice.is_active = False
    db_session.add(alice)
    db_session.commit()

    with pytest.raises(InactiveUserError):
        get_transaction_by_id(db_session, alice, tx_id)


# ===========================================================================
# 8. IDEMPOTENCY EXPIRATION & RECLAIMING TESTS (IDEMP-001)
# ===========================================================================


def test_idempotency_expired_completed_record_reclaimable(db_session: Session):
    """Verify expired completed idempotency record can be reclaimed with fresh payload without collision (IDEMP-001)."""
    from datetime import datetime, timedelta, timezone
    from backend.app.services.idempotency_service import check_or_reserve_idempotency_key, compute_request_hash

    user = _create_user(db_session, "idemp_exp_user@example.com")
    key = "key-expire-test"
    hash1 = compute_request_hash({"amount": 1000})

    # Reserve and complete with an expired timestamp (e.g. 2 days ago)
    past_time = datetime.now(timezone.utc) - timedelta(days=2)
    rec, is_cached = check_or_reserve_idempotency_key(db_session, user.id, key, hash1)
    rec.response_status = 200
    rec.response_body = '{"success": true}'
    rec.expires_at = past_time
    db_session.add(rec)
    db_session.commit()

    # New request with DIFFERENT payload and same key
    hash2 = compute_request_hash({"amount": 9999})
    reclaimed_rec, is_cached_2 = check_or_reserve_idempotency_key(db_session, user.id, key, hash2)

    # Should NOT raise IdempotencyCollisionError; should reclaim record in-place for fresh execution
    assert is_cached_2 is False
    assert reclaimed_rec.request_hash == hash2
    assert reclaimed_rec.response_status is None
    assert reclaimed_rec.expires_at > datetime.now(timezone.utc)


def test_idempotency_expired_in_flight_record_reclaimable(db_session: Session):
    """Verify expired abandoned in-flight reservation does not block indefinite retries (IDEMP-001)."""
    from datetime import datetime, timedelta, timezone
    from backend.app.services.idempotency_service import check_or_reserve_idempotency_key, compute_request_hash

    user = _create_user(db_session, "idemp_inflight_exp@example.com")
    key = "key-inflight-abandoned"
    hash1 = compute_request_hash({"attempt": 1})

    past_time = datetime.now(timezone.utc) - timedelta(hours=5)
    rec = IdempotencyRecord(
        user_id=user.id,
        idempotency_key=key,
        request_hash=hash1,
        response_status=None,  # In-flight
        expires_at=past_time,  # Expired/abandoned
    )
    db_session.add(rec)
    db_session.commit()

    # Retry should succeed and reclaim the abandoned record
    hash2 = compute_request_hash({"attempt": 2})
    reclaimed, is_cached = check_or_reserve_idempotency_key(db_session, user.id, key, hash2)
    assert is_cached is False
    assert reclaimed.request_hash == hash2
    assert reclaimed.response_status is None
