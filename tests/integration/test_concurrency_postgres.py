"""
Integration tests verifying PostgreSQL row-level locking and race-condition prevention.

Targets the approved PostgreSQL test database (ledgerline_test).
Validates:
- Concurrency race test execution: two ₹700 withdrawals from a ₹1000 account.
- SELECT ... FOR UPDATE row-locking correctness in PostgreSQL.
- Overdraft prevention under concurrent execution.
- Total customer money conservation during concurrent transfer races.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import threading
import uuid

import pytest
from sqlalchemy import Engine, delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.exceptions import (
    IdempotencyCollisionError,
    IdempotencyInFlightError,
    InsufficientFundsError,
)
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.audit_event import AuditEvent
from backend.app.models.idempotency import IdempotencyRecord
from backend.app.models.ledger_entry import LedgerEntry
from backend.app.models.transaction import Transaction
from backend.app.models.user import User, UserRole
from backend.app.services.account_service import get_or_create_system_clearing_account
from backend.app.services.idempotency_service import (
    check_or_reserve_idempotency_key,
    save_idempotency_response,
)
from backend.app.services.transaction_service import execute_transfer, execute_withdrawal


def _cleanup_database(conn, created_user_ids=None, created_account_ids=None):
    created_user_ids = created_user_ids or []
    created_account_ids = created_account_ids or []

    # 1. Identify race transactions or transactions initiated by created test users
    tx_conditions = [
        Transaction.reference.like("WTH-race-%"),
        Transaction.reference.like("TRF-race-%"),
    ]
    if created_user_ids:
        tx_conditions.append(Transaction.initiated_by.in_(created_user_ids))

    res = conn.execute(select(Transaction.id).where(or_(*tx_conditions)))
    tx_ids = [row[0] for row in res.fetchall()]

    # 2. Delete ledger entries referencing these transactions or accounts
    le_conditions = []
    if tx_ids:
        le_conditions.append(LedgerEntry.transaction_id.in_(tx_ids))
    if created_account_ids:
        le_conditions.append(LedgerEntry.account_id.in_(created_account_ids))
    if le_conditions:
        conn.execute(delete(LedgerEntry).where(or_(*le_conditions)))

    # 3. Delete transactions
    if tx_ids:
        conn.execute(delete(Transaction).where(Transaction.id.in_(tx_ids)))

    # 4. Delete account memberships
    mem_conditions = []
    if created_account_ids:
        mem_conditions.append(AccountMembership.account_id.in_(created_account_ids))
    if created_user_ids:
        mem_conditions.append(AccountMembership.user_id.in_(created_user_ids))
    if mem_conditions:
        conn.execute(delete(AccountMembership).where(or_(*mem_conditions)))

    # 5. Delete accounts
    if created_account_ids:
        conn.execute(delete(Account).where(Account.id.in_(created_account_ids)))

    # 6. Delete user-scoped records and users
    if created_user_ids:
        conn.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(created_user_ids)))
        conn.execute(delete(AuditEvent).where(AuditEvent.actor_user_id.in_(created_user_ids)))
        conn.execute(delete(User).where(User.id.in_(created_user_ids)))


@pytest.fixture
def pg_session(test_engine: Engine):
    """Provide an isolated session connected to the live PostgreSQL test database."""
    session_factory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = session_factory()
    created_user_ids = []
    created_account_ids = []

    # Clean any stale test transactions from previous interrupted runs
    with test_engine.begin() as conn:
        _cleanup_database(conn)

    yield session, session_factory, created_user_ids, created_account_ids

    # Cleanup test data created during integration tests
    session.rollback()
    with test_engine.begin() as conn:
        _cleanup_database(conn, created_user_ids, created_account_ids)


def test_postgres_concurrent_withdrawal_race_condition(pg_session):
    """Concurrency race test execution: two concurrent ₹700 withdrawals from a ₹1000 account.

    Initial balance: 100,000 paise (₹1,000.00).
    Worker 1 attempts withdrawal of 70,000 paise (₹700.00).
    Worker 2 attempts withdrawal of 70,000 paise (₹700.00).
    PostgreSQL SELECT ... FOR UPDATE guarantees one worker locks the row first.
    The second worker rechecks balance under lock and is rejected with InsufficientFundsError.
    Final balance must be exactly 30,000 paise (₹300.00). Overdraft is prevented.
    """
    db, session_factory, user_ids, account_ids = pg_session

    # 1. Setup User and Account with ₹1,000 balance (100,000 paise)
    user = User(
        email=f"race_user_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="dummy_hash",
        full_name="Race Condition Tester",
        role=UserRole.HOLDER.value,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_ids.append(user.id)

    # Ensure system clearing account exists
    get_or_create_system_clearing_account(db)
    db.commit()

    account = Account(
        account_number=f"LL-RACE-{uuid.uuid4().hex[:8]}",
        account_name="Race Account ₹1000",
        currency="INR",
        balance=100000,  # ₹1000.00
        status=AccountStatus.ACTIVE.value,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    account_ids.append(account.id)

    membership = AccountMembership(
        user_id=user.id,
        account_id=account.id,
        membership_role=MembershipRole.OWNER.value,
    )
    db.add(membership)
    db.commit()

    run_id = uuid.uuid4().hex[:8]
    target_user_id = user.id
    target_account_id = account.id

    # 2. Concurrency Runner
    def _attempt_withdrawal(key_suffix: str) -> str:
        worker_session = session_factory()
        try:
            worker_user = worker_session.get(User, target_user_id)
            execute_withdrawal(
                db=worker_session,
                user=worker_user,
                account_id=target_account_id,
                amount_paise=70000,  # ₹700.00
                idempotency_key=f"race-wth-{run_id}-{key_suffix}",
                description=f"Concurrent ₹700 withdrawal {key_suffix}",
            )
            return "SUCCESS"
        except InsufficientFundsError:
            return "INSUFFICIENT_FUNDS"
        finally:
            worker_session.close()

    # Launch two concurrent workers simultaneously
    results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_attempt_withdrawal, "thread-1"),
            executor.submit(_attempt_withdrawal, "thread-2"),
        ]
        for f in as_completed(futures):
            results.append(f.result())

    # Exactly one must succeed, and exactly one must fail
    assert sorted(results) == ["INSUFFICIENT_FUNDS", "SUCCESS"]

    # 3. Verify final state in PostgreSQL
    db.expire_all()
    refreshed_acc = db.get(Account, account.id)
    assert refreshed_acc.balance == 30000  # Exactly ₹300.00 remaining


def test_postgres_concurrent_transfer_race_condition(pg_session):
    """Verify that two concurrent transfers from a ₹1000 account competing for ₹600 each

    prevents double-spend and leaves the account at ₹400.
    """
    db, session_factory, user_ids, account_ids = pg_session

    alice = User(
        email=f"alice_race_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="dummy_hash",
        full_name="Alice Race",
        role=UserRole.HOLDER.value,
        is_active=True,
    )
    bob = User(
        email=f"bob_race_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="dummy_hash",
        full_name="Bob Race",
        role=UserRole.HOLDER.value,
        is_active=True,
    )
    db.add_all([alice, bob])
    db.commit()
    user_ids.extend([alice.id, bob.id])

    acc_alice = Account(
        account_number=f"LL-ALICE-RACE-{uuid.uuid4().hex[:8]}",
        account_name="Alice ₹1000",
        currency="INR",
        balance=100000,
        status=AccountStatus.ACTIVE.value,
    )
    acc_bob = Account(
        account_number=f"LL-BOB-RACE-{uuid.uuid4().hex[:8]}",
        account_name="Bob ₹0",
        currency="INR",
        balance=0,
        status=AccountStatus.ACTIVE.value,
    )
    db.add_all([acc_alice, acc_bob])
    db.commit()
    account_ids.extend([acc_alice.id, acc_bob.id])

    db.add(AccountMembership(user_id=alice.id, account_id=acc_alice.id, membership_role=MembershipRole.OWNER.value))
    db.add(AccountMembership(user_id=bob.id, account_id=acc_bob.id, membership_role=MembershipRole.OWNER.value))
    db.commit()

    run_id = uuid.uuid4().hex[:8]
    alice_id = alice.id
    acc_alice_id = acc_alice.id
    acc_bob_id = acc_bob.id

    def _attempt_transfer(key_suffix: str) -> str:
        worker_session = session_factory()
        try:
            worker_alice = worker_session.get(User, alice_id)
            execute_transfer(
                db=worker_session,
                user=worker_alice,
                source_account_id=acc_alice_id,
                destination_account_id=acc_bob_id,
                amount_paise=60000,  # ₹600.00
                idempotency_key=f"race-trf-{run_id}-{key_suffix}",
            )
            return "SUCCESS"
        except InsufficientFundsError:
            return "INSUFFICIENT_FUNDS"
        finally:
            worker_session.close()

    results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_attempt_transfer, "trf-1"),
            executor.submit(_attempt_transfer, "trf-2"),
        ]
        for f in as_completed(futures):
            results.append(f.result())

    assert sorted(results) == ["INSUFFICIENT_FUNDS", "SUCCESS"]

    db.expire_all()
    refreshed_alice = db.get(Account, acc_alice.id)
    refreshed_bob = db.get(Account, acc_bob.id)

    assert refreshed_alice.balance == 40000  # 100000 - 60000
    assert refreshed_bob.balance == 60000    # 0 + 60000
    assert refreshed_alice.balance + refreshed_bob.balance == 100000  # Conservation


def test_postgres_concurrent_clearing_account_initialization(pg_session):
    """Verify concurrent threads attempting to initialize SYSTEM_CLEARING handle race cleanly.

    Validates:
    - CONC-001: savepoint rollback prevents outer transaction abort on IntegrityError.
    - All concurrent workers obtain the identical clearing account instance.
    - Exactly one SYSTEM_CLEARING row exists in PostgreSQL accounts table.
    """
    _, session_factory, _, _ = pg_session

    # Delete existing SYSTEM_CLEARING to force concurrent creation race
    with session_factory() as cleanup_session:
        clearing_existing = cleanup_session.execute(
            select(Account).where(Account.account_number == "SYSTEM_CLEARING")
        ).scalar_one_or_none()
        if clearing_existing:
            cleanup_session.execute(delete(LedgerEntry).where(LedgerEntry.account_id == clearing_existing.id))
            cleanup_session.execute(delete(Account).where(Account.id == clearing_existing.id))
            cleanup_session.commit()

    def _init_clearing() -> uuid.UUID:
        worker_session = session_factory()
        try:
            account = get_or_create_system_clearing_account(worker_session)
            worker_session.commit()
            return account.id
        except Exception:
            worker_session.rollback()
            raise
        finally:
            worker_session.close()

    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_init_clearing) for _ in range(4)]
        for f in as_completed(futures):
            results.append(f.result())

    # All 4 concurrent workers must have succeeded
    assert len(results) == 4
    # All must have received the identical account UUID
    assert len(set(results)) == 1

    # Verify exactly one SYSTEM_CLEARING row in PostgreSQL
    with session_factory() as verify_session:
        clearing_rows = verify_session.execute(
            select(Account).where(Account.account_number == "SYSTEM_CLEARING")
        ).scalars().all()
        assert len(clearing_rows) == 1
        assert clearing_rows[0].balance == 0


def test_postgres_concurrent_expired_idempotency_same_payload(pg_session):
    """Verify concurrent workers competing for the same expired key with identical payload.

    Validates:
    - Exactly one worker reclaims and executes (is_cached=False).
    - The competing worker waits on the row lock and receives the committed cached response (is_cached=True).
    - Total operations executed == 1; database row persists the single committed response.
    """
    db, session_factory, user_ids, _ = pg_session

    user = User(
        email=f"idemp_same_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="dummy_hash",
        full_name="Idemp Same",
        role=UserRole.HOLDER.value,
        is_active=True,
    )
    db.add(user)
    db.commit()
    user_ids.append(user.id)
    user_id = user.id

    key = f"same-exp-{uuid.uuid4().hex[:8]}"
    past = datetime.now(timezone.utc) - timedelta(hours=3)

    # Insert an expired completed record
    with session_factory() as setup_session:
        setup_session.add(
            IdempotencyRecord(
                user_id=user_id,
                idempotency_key=key,
                request_hash="old-hash",
                response_status=200,
                response_body='{"old": true}',
                expires_at=past,
            )
        )
        setup_session.commit()

    barrier = threading.Barrier(2)
    results = {}
    payload_hash = "shared-request-hash-12345"

    def worker_1():
        ws = session_factory()
        try:
            record, is_cached = check_or_reserve_idempotency_key(
                db=ws,
                user_id=user_id,
                idempotency_key=key,
                request_hash=payload_hash,
            )
            barrier.wait(timeout=5.0)
            # Simulate financial execution delay while holding row lock
            threading.Event().wait(0.15)
            save_idempotency_response(ws, record, status_code=200, response_body={"status": "POSTED", "ref": "DEP-1"})
            ws.commit()
            results["w1"] = (is_cached, record.request_hash, record.response_status)
        except Exception as e:
            ws.rollback()
            results["w1"] = (type(e).__name__, str(e))
        finally:
            ws.close()

    def worker_2():
        ws = session_factory()
        try:
            # Wait for worker 1 to enter check_or_reserve before attempting
            barrier.wait(timeout=5.0)
            threading.Event().wait(0.02)
            record, is_cached = check_or_reserve_idempotency_key(
                db=ws,
                user_id=user_id,
                idempotency_key=key,
                request_hash=payload_hash,
            )
            ws.commit()
            results["w2"] = (is_cached, record.request_hash, record.response_status)
        except Exception as e:
            ws.rollback()
            results["w2"] = (type(e).__name__, str(e))
        finally:
            ws.close()

    t1 = threading.Thread(target=worker_1)
    t2 = threading.Thread(target=worker_2)
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    # Worker 1 acquired reservation and executed fresh
    assert results["w1"] == (False, payload_hash, 200)
    # Worker 2 waited on row lock and received cached response
    assert results["w2"] == (True, payload_hash, 200)

    # Verify final persisted database state
    with session_factory() as verify_session:
        records = verify_session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.idempotency_key == key,
            )
        ).scalars().all()
        assert len(records) == 1
        persisted = records[0]
        assert persisted.request_hash == payload_hash
        assert persisted.response_status == 200
        assert "DEP-1" in persisted.response_body
        assert persisted.expires_at > datetime.now(timezone.utc)


def test_postgres_concurrent_expired_idempotency_different_payloads(pg_session):
    """Verify concurrent workers competing for an expired key with differing payloads.

    Validates:
    - Worker 1 reclaims and executes (is_cached=False).
    - Worker 2 waits on the row lock and receives IdempotencyCollisionError upon unblocking.
    - Worker 2's conflicting payload does NOT overwrite Worker 1's active reservation.
    """
    db, session_factory, user_ids, _ = pg_session

    user = User(
        email=f"idemp_diff_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="dummy_hash",
        full_name="Idemp Diff",
        role=UserRole.HOLDER.value,
        is_active=True,
    )
    db.add(user)
    db.commit()
    user_ids.append(user.id)
    user_id = user.id

    key = f"diff-exp-{uuid.uuid4().hex[:8]}"
    past = datetime.now(timezone.utc) - timedelta(hours=3)

    with session_factory() as setup_session:
        setup_session.add(
            IdempotencyRecord(
                user_id=user_id,
                idempotency_key=key,
                request_hash="old-hash-initial",
                response_status=200,
                response_body='{"old": 2}',
                expires_at=past,
            )
        )
        setup_session.commit()

    barrier = threading.Barrier(2)
    results = {}
    hash_w1 = "payload-hash-alpha"
    hash_w2 = "payload-hash-beta"

    def worker_1():
        ws = session_factory()
        try:
            record, is_cached = check_or_reserve_idempotency_key(
                db=ws,
                user_id=user_id,
                idempotency_key=key,
                request_hash=hash_w1,
            )
            barrier.wait(timeout=5.0)
            threading.Event().wait(0.15)
            save_idempotency_response(ws, record, status_code=200, response_body={"status": "POSTED", "ref": "WTH-ALPHA"})
            ws.commit()
            results["w1"] = (is_cached, record.request_hash, record.response_status)
        except Exception as e:
            ws.rollback()
            results["w1"] = (type(e).__name__, str(e))
        finally:
            ws.close()

    def worker_2():
        ws = session_factory()
        try:
            barrier.wait(timeout=5.0)
            threading.Event().wait(0.02)
            record, is_cached = check_or_reserve_idempotency_key(
                db=ws,
                user_id=user_id,
                idempotency_key=key,
                request_hash=hash_w2,
            )
            ws.commit()
            results["w2"] = (is_cached, record.request_hash, record.response_status)
        except IdempotencyCollisionError as exc:
            ws.rollback()
            results["w2"] = ("IdempotencyCollisionError", str(exc))
        except Exception as e:
            ws.rollback()
            results["w2"] = (type(e).__name__, str(e))
        finally:
            ws.close()

    t1 = threading.Thread(target=worker_1)
    t2 = threading.Thread(target=worker_2)
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert results["w1"] == (False, hash_w1, 200)
    assert results["w2"][0] == "IdempotencyCollisionError"
    assert "previously used with different parameters" in results["w2"][1]

    # Verify database was NOT corrupted or overwritten by worker 2
    with session_factory() as verify_session:
        records = verify_session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.idempotency_key == key,
            )
        ).scalars().all()
        assert len(records) == 1
        persisted = records[0]
        assert persisted.request_hash == hash_w1
        assert persisted.response_status == 200
        assert "WTH-ALPHA" in persisted.response_body


def test_postgres_concurrent_idempotency_in_flight_protection(pg_session):
    """Verify a second worker cannot acquire a reservation while the first remains uncommitted/in-flight.

    Validates:
    - Worker 2 is blocked by PostgreSQL row lock while Worker 1 is in-flight.
    - Worker 2 cannot complete reservation before Worker 1 commits.
    - When Worker 1 commits, Worker 2 safely resolves to the committed cached response.
    """
    db, session_factory, user_ids, _ = pg_session

    user = User(
        email=f"idemp_inflight_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="dummy_hash",
        full_name="Idemp InFlight",
        role=UserRole.HOLDER.value,
        is_active=True,
    )
    db.add(user)
    db.commit()
    user_ids.append(user.id)
    user_id = user.id

    key = f"inflight-exp-{uuid.uuid4().hex[:8]}"
    past = datetime.now(timezone.utc) - timedelta(hours=3)

    with session_factory() as setup_session:
        setup_session.add(
            IdempotencyRecord(
                user_id=user_id,
                idempotency_key=key,
                request_hash="old-inflight-hash",
                response_status=200,
                response_body='{"old": 3}',
                expires_at=past,
            )
        )
        setup_session.commit()

    barrier = threading.Barrier(2)
    w1_committed_event = threading.Event()
    results = {}
    payload_hash = "inflight-test-hash"

    def worker_1():
        ws = session_factory()
        try:
            record, is_cached = check_or_reserve_idempotency_key(
                db=ws,
                user_id=user_id,
                idempotency_key=key,
                request_hash=payload_hash,
            )
            barrier.wait(timeout=5.0)
            # Hold the uncommitted transaction open
            threading.Event().wait(0.25)
            save_idempotency_response(ws, record, status_code=200, response_body={"status": "POSTED", "ref": "INFLIGHT-SUCCESS"})
            ws.commit()
            w1_committed_event.set()
            results["w1"] = (is_cached, record.request_hash)
        except Exception as e:
            ws.rollback()
            results["w1"] = (type(e).__name__, str(e))
        finally:
            ws.close()

    def worker_2():
        ws = session_factory()
        try:
            barrier.wait(timeout=5.0)
            threading.Event().wait(0.02)
            # When worker 2 calls check_or_reserve, it must block until worker 1 commits
            record, is_cached = check_or_reserve_idempotency_key(
                db=ws,
                user_id=user_id,
                idempotency_key=key,
                request_hash=payload_hash,
            )
            # Worker 2 must have finished strictly AFTER worker 1 committed
            w1_was_committed = w1_committed_event.is_set()
            ws.commit()
            results["w2"] = (is_cached, record.request_hash, w1_was_committed)
        except Exception as e:
            ws.rollback()
            results["w2"] = (type(e).__name__, str(e))
        finally:
            ws.close()

    t1 = threading.Thread(target=worker_1)
    t2 = threading.Thread(target=worker_2)
    t1.start()
    t2.start()
    t1.join(timeout=10.0)
    t2.join(timeout=10.0)

    assert results["w1"] == (False, payload_hash)
    # Worker 2 unblocked only after Worker 1 committed, and received the cached replay
    assert results["w2"] == (True, payload_hash, True)

    with session_factory() as verify_session:
        records = verify_session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.idempotency_key == key,
            )
        ).scalars().all()
        assert len(records) == 1
        persisted = records[0]
        assert persisted.request_hash == payload_hash
        assert persisted.response_status == 200
        assert "INFLIGHT-SUCCESS" in persisted.response_body
