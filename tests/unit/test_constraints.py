"""
Database constraint and relationship enforcement tests using an isolated SQLite in-memory engine.

Verifies runtime enforcement of:
- Negative account balance rejection.
- Zero and negative transaction amount rejection.
- Zero and negative ledger-entry amount rejection.
- Invalid enum string check constraints (UserRole, AccountStatus, TransactionType, EntryType, etc.).
- Duplicate account membership rejection.
- Bidirectional ORM relationship back-population.
"""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.account import Account
from backend.app.models.account_membership import AccountMembership
from backend.app.models.base import Base
from backend.app.models.ledger_entry import LedgerEntry
from backend.app.models.session import Session as UserSession
from backend.app.models.transaction import Transaction
from backend.app.models.user import User


@pytest.fixture
def sqlite_session():
    """Provide an isolated SQLite in-memory session with foreign-key enforcement enabled."""
    engine = create_engine("sqlite:///:memory:")

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


def test_negative_account_balance_rejection(sqlite_session: Session):
    """Verify check constraint rejects negative balances (ck_accounts_balance_non_negative)."""
    # Negative balance must fail
    invalid_account = Account(
        account_number="ACC-NEG-001",
        account_name="Negative Test",
        balance=-100,
    )
    sqlite_session.add(invalid_account)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # Zero balance must succeed
    valid_zero_account = Account(
        account_number="ACC-ZERO-001",
        account_name="Zero Test",
        balance=0,
    )
    sqlite_session.add(valid_zero_account)
    sqlite_session.commit()
    assert valid_zero_account.id is not None
    assert valid_zero_account.balance == 0


def test_zero_or_negative_transaction_amount_rejection(sqlite_session: Session):
    """Verify check constraint rejects zero and negative amounts (ck_transactions_amount_paise_positive)."""
    # Zero amount must fail
    zero_tx = Transaction(
        reference="TX-ZERO-001",
        transaction_type="DEPOSIT",
        amount_paise=0,
    )
    sqlite_session.add(zero_tx)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # Negative amount must fail
    neg_tx = Transaction(
        reference="TX-NEG-001",
        transaction_type="DEPOSIT",
        amount_paise=-5000,
    )
    sqlite_session.add(neg_tx)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # Positive amount must succeed
    valid_tx = Transaction(
        reference="TX-VALID-001",
        transaction_type="DEPOSIT",
        amount_paise=5000,
    )
    sqlite_session.add(valid_tx)
    sqlite_session.commit()
    assert valid_tx.id is not None


def test_zero_or_negative_ledger_entry_amount_rejection(sqlite_session: Session):
    """Verify check constraint rejects zero and negative amounts (ck_ledger_entries_amount_paise_positive)."""
    # Setup valid parent account and transaction
    account = Account(account_number="ACC-LEDGER-001", account_name="Ledger Test", balance=1000)
    tx = Transaction(reference="TX-LEDGER-001", transaction_type="DEPOSIT", amount_paise=1000)
    sqlite_session.add_all([account, tx])
    sqlite_session.commit()

    # Zero amount ledger entry must fail
    zero_entry = LedgerEntry(
        transaction_id=tx.id,
        account_id=account.id,
        entry_type="CREDIT",
        amount_paise=0,
    )
    sqlite_session.add(zero_entry)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # Negative amount ledger entry must fail
    neg_entry = LedgerEntry(
        transaction_id=tx.id,
        account_id=account.id,
        entry_type="DEBIT",
        amount_paise=-1000,
    )
    sqlite_session.add(neg_entry)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # Positive amount ledger entry must succeed
    pos_entry = LedgerEntry(
        transaction_id=tx.id,
        account_id=account.id,
        entry_type="CREDIT",
        amount_paise=1000,
    )
    sqlite_session.add(pos_entry)
    sqlite_session.commit()
    assert pos_entry.id is not None


def test_invalid_role_and_status_check_constraints(sqlite_session: Session):
    """Verify check constraints reject unapproved enum string values across all models."""
    # 1. User with invalid role
    invalid_user = User(
        email="invalid-role@test.com",
        password_hash="hash",
        full_name="Invalid Role",
        role="SUPERADMIN",
    )
    sqlite_session.add(invalid_user)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # 2. Account with invalid status
    invalid_acc = Account(
        account_number="ACC-INV-STAT",
        account_name="Invalid Status",
        status="DELETED",
    )
    sqlite_session.add(invalid_acc)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # 3. Transaction with invalid transaction_type
    invalid_tx_type = Transaction(
        reference="TX-INV-TYPE",
        transaction_type="REFUND",
        amount_paise=1000,
    )
    sqlite_session.add(invalid_tx_type)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # 4. Transaction with invalid status
    invalid_tx_status = Transaction(
        reference="TX-INV-STAT",
        transaction_type="DEPOSIT",
        status="ARCHIVED",
        amount_paise=1000,
    )
    sqlite_session.add(invalid_tx_status)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # 5. LedgerEntry with invalid entry_type
    acc = Account(account_number="ACC-LE-INV", account_name="LE Inv", balance=500)
    tx = Transaction(reference="TX-LE-INV", transaction_type="DEPOSIT", amount_paise=500)
    sqlite_session.add_all([acc, tx])
    sqlite_session.commit()

    invalid_le = LedgerEntry(
        transaction_id=tx.id,
        account_id=acc.id,
        entry_type="TRANSFER",
        amount_paise=500,
    )
    sqlite_session.add(invalid_le)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()

    # 6. AccountMembership with invalid membership_role
    u = User(email="valid@test.com", password_hash="h", full_name="Valid", role="HOLDER")
    sqlite_session.add(u)
    sqlite_session.commit()

    invalid_mem = AccountMembership(
        user_id=u.id,
        account_id=acc.id,
        membership_role="GUEST",
    )
    sqlite_session.add(invalid_mem)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()


def test_duplicate_account_membership_rejection(sqlite_session: Session):
    """Verify unique constraint uq_account_memberships_user_account prevents duplicate memberships."""
    u = User(email="member@test.com", password_hash="h", full_name="Member", role="HOLDER")
    acc = Account(account_number="ACC-MEM-001", account_name="Membership Acc", balance=0)
    sqlite_session.add_all([u, acc])
    sqlite_session.commit()

    # First membership succeeds
    m1 = AccountMembership(user_id=u.id, account_id=acc.id, membership_role="OWNER")
    sqlite_session.add(m1)
    sqlite_session.commit()

    # Duplicate membership for the same user and account must fail
    m2 = AccountMembership(user_id=u.id, account_id=acc.id, membership_role="VIEWER")
    sqlite_session.add(m2)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()


def test_orm_relationship_back_population(sqlite_session: Session):
    """Verify bidirectional ORM back_populates linkage across models."""
    user = User(email="backpop@test.com", password_hash="hash", full_name="BackPop User")
    account = Account(account_number="ACC-BACKPOP-001", account_name="BackPop Acc", balance=5000)
    sqlite_session.add_all([user, account])
    sqlite_session.commit()

    # 1. User <-> Session back_populates
    session = UserSession(
        token_hash="token_hash_backpop_12345",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    user.sessions.append(session)
    assert session.user == user
    assert session in user.sessions

    # 2. User & Account <-> AccountMembership back_populates
    membership = AccountMembership(
        user=user,
        account=account,
        membership_role="OWNER",
    )
    sqlite_session.add(membership)
    assert membership.user == user
    assert membership.account == account
    assert membership in user.memberships
    assert membership in account.memberships

    # 3. User <-> Transaction (initiated_by) back_populates
    tx = Transaction(
        reference="TX-BACKPOP-001",
        transaction_type="TRANSFER",
        amount_paise=2500,
    )
    user.initiated_transactions.append(tx)
    assert tx.initiator == user

    # 4. Transaction & Account <-> LedgerEntry back_populates
    entry = LedgerEntry(
        entry_type="DEBIT",
        amount_paise=2500,
        account=account,
    )
    tx.ledger_entries.append(entry)
    assert entry.transaction == tx
    assert entry in tx.ledger_entries
    assert entry in account.ledger_entries

    # Persist and flush all to verify foreign key integrity
    sqlite_session.commit()
    assert session.id is not None
    assert membership.id is not None
    assert tx.id is not None
    assert entry.id is not None
