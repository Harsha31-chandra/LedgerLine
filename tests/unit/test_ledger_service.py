"""
Unit tests for LedgerLine double-entry ledger posting and reconciliation engine.

Covers:
- Mathematical double-entry balance verification: sum(Debits) == sum(Credits).
- Strict positive integer amount validation.
- Insufficient balance enforcement on debit account.
- Currency mismatch rejection.
- Independent balance reconciliation against posted journal entries.
- Detection of balance snapshot discrepancies.
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.exceptions import (
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidAmountError,
)
from backend.app.models.account import Account, AccountStatus
from backend.app.models.base import Base
from backend.app.models.ledger_entry import EntryType, LedgerEntry
from backend.app.models.transaction import TransactionType
from backend.app.services.ledger_service import (
    post_ledger_transaction,
    reconcile_account_balance,
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


def _create_account(
    db: Session,
    account_number: str,
    balance: int = 100000,
    currency: str = "INR",
) -> Account:
    account = Account(
        account_number=account_number,
        account_name=f"Account {account_number}",
        currency=currency,
        balance=balance,
        status=AccountStatus.ACTIVE.value,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def test_post_ledger_transaction_success(db_session: Session):
    """Verify posting a balanced double-entry transaction updates balances and creates entries."""
    acc_a = _create_account(db_session, "ACC-A-01", balance=50000)
    acc_b = _create_account(db_session, "ACC-B-01", balance=10000)

    amount = 15000  # 150.00 INR
    tx = post_ledger_transaction(
        db=db_session,
        transaction_type=TransactionType.TRANSFER,
        amount_paise=amount,
        debit_account=acc_a,
        credit_account=acc_b,
        reference="TX-LEDGER-001",
        description="Transfer test",
    )
    db_session.commit()

    assert tx.id is not None
    assert tx.reference == "TX-LEDGER-001"
    assert tx.amount_paise == amount
    assert tx.status == "POSTED"

    # Verify account balance snapshots
    db_session.refresh(acc_a)
    db_session.refresh(acc_b)
    assert acc_a.balance == 35000  # 50000 - 15000
    assert acc_b.balance == 25000  # 10000 + 15000

    # Verify double-entry ledger entries
    entries = db_session.query(LedgerEntry).filter_by(transaction_id=tx.id).all()
    assert len(entries) == 2

    debits = [e for e in entries if e.entry_type == EntryType.DEBIT.value]
    credits = [e for e in entries if e.entry_type == EntryType.CREDIT.value]

    assert len(debits) == 1
    assert len(credits) == 1
    assert debits[0].account_id == acc_a.id
    assert debits[0].amount_paise == amount
    assert credits[0].account_id == acc_b.id
    assert credits[0].amount_paise == amount


def test_post_ledger_transaction_insufficient_funds(db_session: Session):
    """Verify attempting to debit more than the account balance raises InsufficientFundsError."""
    acc_a = _create_account(db_session, "ACC-POOR-01", balance=5000)
    acc_b = _create_account(db_session, "ACC-DEST-01", balance=0)

    with pytest.raises(InsufficientFundsError):
        post_ledger_transaction(
            db=db_session,
            transaction_type=TransactionType.TRANSFER,
            amount_paise=10000,
            debit_account=acc_a,
            credit_account=acc_b,
            reference="TX-FAIL-FUNDS",
        )

    # Verify zero balance changes
    db_session.refresh(acc_a)
    db_session.refresh(acc_b)
    assert acc_a.balance == 5000
    assert acc_b.balance == 0


def test_post_ledger_transaction_invalid_amount(db_session: Session):
    """Verify zero and negative amounts are rejected."""
    acc_a = _create_account(db_session, "ACC-INV-A", balance=50000)
    acc_b = _create_account(db_session, "ACC-INV-B", balance=50000)

    with pytest.raises(InvalidAmountError):
        post_ledger_transaction(
            db=db_session,
            transaction_type=TransactionType.TRANSFER,
            amount_paise=0,
            debit_account=acc_a,
            credit_account=acc_b,
            reference="TX-ZERO",
        )

    with pytest.raises(InvalidAmountError):
        post_ledger_transaction(
            db=db_session,
            transaction_type=TransactionType.TRANSFER,
            amount_paise=-500,
            debit_account=acc_a,
            credit_account=acc_b,
            reference="TX-NEG",
        )


def test_post_ledger_transaction_currency_mismatch(db_session: Session):
    """Verify mismatched currencies between accounts are rejected."""
    acc_inr = _create_account(db_session, "ACC-INR-01", balance=50000, currency="INR")
    acc_usd = _create_account(db_session, "ACC-USD-01", balance=50000, currency="USD")

    with pytest.raises(CurrencyMismatchError):
        post_ledger_transaction(
            db=db_session,
            transaction_type=TransactionType.TRANSFER,
            amount_paise=1000,
            debit_account=acc_inr,
            credit_account=acc_usd,
            reference="TX-CURRENCY-ERR",
        )


def test_reconcile_account_balance_success(db_session: Session):
    """Verify reconcile_account_balance proves derived balance equals cached snapshot."""
    acc_source = _create_account(db_session, "ACC-SRC-REC", balance=100000)
    acc_target = _create_account(db_session, "ACC-TGT-REC", balance=0)

    # 1. Post transfer 30000
    post_ledger_transaction(
        db_session,
        TransactionType.TRANSFER,
        30000,
        acc_source,
        acc_target,
        "TX-REC-1",
    )
    # 2. Post transfer 20000
    post_ledger_transaction(
        db_session,
        TransactionType.TRANSFER,
        20000,
        acc_source,
        acc_target,
        "TX-REC-2",
    )
    # 3. Post transfer back 5000
    post_ledger_transaction(
        db_session,
        TransactionType.TRANSFER,
        5000,
        acc_target,
        acc_source,
        "TX-REC-3",
    )
    db_session.commit()

    # Reconcile target: Credits = 30000 + 20000 = 50000, Debits = 5000 -> Derived = 45000
    cached, derived, is_reconciled = reconcile_account_balance(db_session, acc_target.id)
    assert cached == 45000
    assert derived == 45000
    assert is_reconciled is True

    # Reconcile source: Initial was 100000, debited 50000, credited 5000 -> balance 55000
    # Note: For accounts with initial balance created outside ledger, derived is from ledger entries.
    cached_src, derived_src, _ = reconcile_account_balance(db_session, acc_source.id)
    assert cached_src == 55000
    assert derived_src == -45000  # 5000 credits - 50000 debits


def test_reconcile_account_balance_tamper_detection(db_session: Session):
    """Verify that tampering with cached balance snapshot is detected by reconciliation."""
    acc = _create_account(db_session, "ACC-TAMPER-01", balance=0)
    vault = _create_account(db_session, "ACC-VAULT-01", balance=1000000)

    post_ledger_transaction(
        db_session,
        TransactionType.DEPOSIT,
        25000,
        vault,
        acc,
        "TX-TAMPER-01",
    )
    db_session.commit()

    cached, derived, is_reconciled = reconcile_account_balance(db_session, acc.id)
    assert is_reconciled is True
    assert cached == 25000

    # Attacker directly alters accounts.balance row
    acc.balance = 999999
    db_session.add(acc)
    db_session.commit()

    cached_tampered, derived_ledger, is_reconciled_after = reconcile_account_balance(db_session, acc.id)
    assert cached_tampered == 999999
    assert derived_ledger == 25000
    assert is_reconciled_after is False  # Discrepancy successfully detected!


def test_clearing_account_initial_reconciliation_zero(db_session: Session):
    """Verify newly initialized clearing account starts at 0 and reconciles immediately."""
    from backend.app.services.account_service import get_or_create_system_clearing_account

    clearing = get_or_create_system_clearing_account(db_session)
    db_session.commit()

    cached, derived, is_reconciled = reconcile_account_balance(db_session, clearing.id)
    assert cached == 0
    assert derived == 0
    assert is_reconciled is True


def test_clearing_account_deposit_and_withdrawal_reconciliation(db_session: Session):
    """Verify deposits and withdrawals reconcile both customer and clearing balances.

    Ensures zero fabricated money and strict double-entry balance conservation.
    """
    from backend.app.services.account_service import get_or_create_system_clearing_account

    clearing = get_or_create_system_clearing_account(db_session)
    customer = _create_account(db_session, "CUST-REC-01", balance=0)
    db_session.commit()

    # 1. Customer deposits 10,000 paise (₹100)
    # Double-entry: Debit clearing (10000), Credit customer (10000)
    post_ledger_transaction(
        db=db_session,
        transaction_type=TransactionType.DEPOSIT,
        amount_paise=10000,
        debit_account=clearing,
        credit_account=customer,
        reference="DEP-001",
    )
    db_session.commit()

    # Verify customer reconciles
    cust_cached, cust_derived, cust_rec = reconcile_account_balance(db_session, customer.id)
    assert cust_cached == 10000
    assert cust_derived == 10000
    assert cust_rec is True

    # Verify clearing account reconciles (derived = credits - debits = 0 - 10000 = -10000)
    clr_cached, clr_derived, clr_rec = reconcile_account_balance(db_session, clearing.id)
    assert clr_cached == -10000
    assert clr_derived == -10000
    assert clr_rec is True

    # Conservation invariant: customer balance + clearing balance == 0
    assert cust_cached + clr_cached == 0

    # 2. Customer withdraws 4,000 paise (₹40)
    # Double-entry: Debit customer (4000), Credit clearing (4000)
    post_ledger_transaction(
        db=db_session,
        transaction_type=TransactionType.WITHDRAWAL,
        amount_paise=4000,
        debit_account=customer,
        credit_account=clearing,
        reference="WTH-001",
    )
    db_session.commit()

    # Customer: 10000 - 4000 = 6000
    cust_cached, cust_derived, cust_rec = reconcile_account_balance(db_session, customer.id)
    assert cust_cached == 6000
    assert cust_derived == 6000
    assert cust_rec is True

    # Clearing: -10000 + 4000 = -6000 (Credits=4000, Debits=10000 -> -6000)
    clr_cached, clr_derived, clr_rec = reconcile_account_balance(db_session, clearing.id)
    assert clr_cached == -6000
    assert clr_derived == -6000
    assert clr_rec is True

    # Conservation invariant remains exactly 0
    assert cust_cached + clr_cached == 0


def test_customer_account_overdraw_prevented(db_session: Session):
    """Verify customer account cannot be debited below zero even though clearing account can."""
    from backend.app.services.account_service import get_or_create_system_clearing_account

    clearing = get_or_create_system_clearing_account(db_session)
    customer = _create_account(db_session, "CUST-OVERDRAW", balance=5000)

    # Attempt withdrawal of 6000 (customer only has 5000)
    with pytest.raises(InsufficientFundsError):
        post_ledger_transaction(
            db=db_session,
            transaction_type=TransactionType.WITHDRAWAL,
            amount_paise=6000,
            debit_account=customer,
            credit_account=clearing,
            reference="FAIL-OVERDRAW",
        )

    # Balance remains intact
    db_session.refresh(customer)
    assert customer.balance == 5000
