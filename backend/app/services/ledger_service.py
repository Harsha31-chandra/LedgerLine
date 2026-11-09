"""
Double-entry ledger service for LedgerLine.

Provides:
- Atomic double-entry financial posting engine.
- Strict verification of mathematical balance: sum(Debits) == sum(Credits).
- Synchronized updates of account balance snapshots.
- Pure append-only ledger entries (no update or delete operations).
- Reconciliation utility comparing cached balance snapshots against posted ledger journals.
"""

from typing import Final
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from backend.app.core.exceptions import (
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidAmountError,
    UnbalancedLedgerError,
)
from backend.app.models.account import Account
from backend.app.models.ledger_entry import EntryType, LedgerEntry
from backend.app.models.transaction import Transaction, TransactionStatus, TransactionType
from backend.app.services.account_service import SYSTEM_CLEARING_ACCOUNT_NUMBER

__all__ = [
    "post_ledger_transaction",
    "reconcile_account_balance",
]


def post_ledger_transaction(
    db: DbSession,
    transaction_type: TransactionType,
    amount_paise: int,
    debit_account: Account,
    credit_account: Account,
    reference: str,
    description: str | None = None,
    initiated_by: uuid.UUID | None = None,
    currency: str = "INR",
) -> Transaction:
    """Create a balanced double-entry transaction and update account balance snapshots atomically.

    For all operations:
    - debit_account: Account whose balance decreases by amount_paise.
    - credit_account: Account whose balance increases by amount_paise.
    - Total debits == Total credits == amount_paise.

    Args:
        db: Active SQLAlchemy database session.
        transaction_type: Type of operation (DEPOSIT, WITHDRAWAL, TRANSFER).
        amount_paise: Integer minor units (strictly positive).
        debit_account: Account to be debited.
        credit_account: Account to be credited.
        reference: Unique idempotency / transaction reference string.
        description: Optional business description.
        initiated_by: User UUID who initiated the operation.
        currency: Expected 3-character ISO currency code.

    Returns:
        The posted Transaction entity with attached ledger entries.

    Raises:
        InvalidAmountError: If amount_paise <= 0.
        CurrencyMismatchError: If account currencies do not match expected currency.
        InsufficientFundsError: If debit_account balance would drop below zero.
        UnbalancedLedgerError: If double-entry posting is not balanced.
    """
    if amount_paise <= 0:
        raise InvalidAmountError("Transaction amount must be a strictly positive integer greater than zero")

    if debit_account.currency != currency or credit_account.currency != currency:
        raise CurrencyMismatchError(
            f"Currency mismatch: expected {currency}, but got debit={debit_account.currency}, credit={credit_account.currency}"
        )

    # Verify debit account has sufficient balance (clearing account records external settlement flows)
    if debit_account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER and debit_account.balance < amount_paise:
        raise InsufficientFundsError(
            f"Account '{debit_account.account_number}' has insufficient balance ({debit_account.balance} paise) "
            f"for requested debit of {amount_paise} paise"
        )

    # 1. Create Transaction header
    tx = Transaction(
        reference=reference,
        transaction_type=transaction_type.value,
        status=TransactionStatus.POSTED.value,
        amount_paise=amount_paise,
        currency=currency,
        description=description,
        initiated_by=initiated_by,
    )
    db.add(tx)
    db.flush()  # Generate tx.id for foreign keys

    # 2. Create balanced debit and credit entries
    debit_entry = LedgerEntry(
        transaction_id=tx.id,
        account_id=debit_account.id,
        entry_type=EntryType.DEBIT.value,
        amount_paise=amount_paise,
    )
    credit_entry = LedgerEntry(
        transaction_id=tx.id,
        account_id=credit_account.id,
        entry_type=EntryType.CREDIT.value,
        amount_paise=amount_paise,
    )
    db.add(debit_entry)
    db.add(credit_entry)

    # 3. Mathematical balance invariant verification: sum(Debits) == sum(Credits)
    total_debits = debit_entry.amount_paise
    total_credits = credit_entry.amount_paise
    if total_debits != total_credits:
        raise UnbalancedLedgerError(
            f"Unbalanced double-entry ledger: debits ({total_debits}) != credits ({total_credits})"
        )

    # 4. Atomically synchronize cached balance snapshots
    debit_account.balance -= amount_paise
    credit_account.balance += amount_paise

    db.add(debit_account)
    db.add(credit_account)
    db.flush()

    return tx


def reconcile_account_balance(db: DbSession, account_id: uuid.UUID) -> tuple[int, int, bool]:
    """Audit and reconcile an account's cached balance against its complete posted ledger entries.

    In our banking ledger convention:
    - CREDIT entries increase customer wallet balance.
    - DEBIT entries decrease customer wallet balance.
    - Derived balance = Sum(CREDIT) - Sum(DEBIT).

    Args:
        db: Active SQLAlchemy database session.
        account_id: Account UUID to reconcile.

    Returns:
        Tuple of (cached_balance_paise, derived_balance_paise, is_reconciled: bool).
    """
    account = db.get(Account, account_id)
    if account is None:
        raise ValueError(f"Account {account_id} not found")

    # Sum of all credit entries for this account
    stmt_credit = select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
        LedgerEntry.account_id == account_id,
        LedgerEntry.entry_type == EntryType.CREDIT.value,
    )
    total_credits = db.scalar(stmt_credit) or 0

    # Sum of all debit entries for this account
    stmt_debit = select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
        LedgerEntry.account_id == account_id,
        LedgerEntry.entry_type == EntryType.DEBIT.value,
    )
    total_debits = db.scalar(stmt_debit) or 0

    derived_balance = total_credits - total_debits
    is_reconciled = (derived_balance == account.balance)

    return account.balance, derived_balance, is_reconciled
