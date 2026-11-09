"""
Financial transaction service for LedgerLine.

Coordinates:
- Deposits, withdrawals, and peer-to-peer transfers with strict integer-paise calculations.
- Exactly-once execution via user-scoped idempotency keys and canonical payload hashing.
- Deterministic account-row locking (SELECT FOR UPDATE) in sorted UUID order to prevent deadlocks and race conditions.
- Balanced double-entry posting through ledger_service.
- Integrated audit logging and atomic database commits.
"""

import json
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from backend.app.core.exceptions import (
    AccountNotFoundError,
    AccountStatusError,
    ClearingAccountTransferError,
    CurrencyMismatchError,
    InactiveUserError,
    InsufficientFundsError,
    InvalidAmountError,
    SameAccountTransferError,
)
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership
from backend.app.models.ledger_entry import EntryType, LedgerEntry
from backend.app.models.transaction import Transaction, TransactionStatus, TransactionType
from backend.app.models.user import User
from backend.app.schemas.transaction import (
    AccountStatementItem,
    AccountStatementResponse,
    LedgerEntryResponse,
    TransactionResponse,
)
from backend.app.services.account_service import (
    SYSTEM_CLEARING_ACCOUNT_NUMBER,
    get_or_create_system_clearing_account,
)
from backend.app.services.audit_service import record_audit_event
from backend.app.services.authorization_service import (
    AccountAction,
    check_account_permission,
    get_account_membership,
)
from backend.app.services.idempotency_service import (
    check_or_reserve_idempotency_key,
    compute_request_hash,
    save_idempotency_response,
)
from backend.app.services.ledger_service import post_ledger_transaction

__all__ = [
    "execute_deposit",
    "execute_transfer",
    "execute_withdrawal",
    "get_account_statement",
    "get_transaction_by_id",
]


def _lock_account(db: DbSession, account_id: uuid.UUID) -> Account:
    """Fetch an account with a pessimistic row-level exclusive lock (FOR UPDATE)."""
    stmt = (
        select(Account)
        .where(Account.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    acc = db.scalars(stmt).first()
    if acc is None:
        raise AccountNotFoundError(f"Account {account_id} not found")
    return acc


def _lock_accounts_in_order(db: DbSession, id1: uuid.UUID, id2: uuid.UUID) -> tuple[Account, Account]:
    """Lock two accounts in deterministic order (sorted by UUID) to eliminate deadlock hazards."""
    first_id, second_id = sorted([id1, id2])
    acc_first = _lock_account(db, first_id)
    acc_second = _lock_account(db, second_id)

    if acc_first.id == id1:
        return acc_first, acc_second
    return acc_second, acc_first


def _build_transaction_response(tx: Transaction) -> dict[str, Any]:
    """Serialize a Transaction entity into a clean response dictionary."""
    return {
        "id": str(tx.id),
        "reference": tx.reference,
        "transaction_type": tx.transaction_type,
        "status": tx.status,
        "amount_paise": tx.amount_paise,
        "currency": tx.currency,
        "description": tx.description,
        "initiated_by": str(tx.initiated_by) if tx.initiated_by else None,
        "created_at": tx.created_at.isoformat(),
        "ledger_entries": [
            {
                "id": str(e.id),
                "transaction_id": str(e.transaction_id),
                "account_id": str(e.account_id),
                "entry_type": e.entry_type,
                "amount_paise": e.amount_paise,
                "created_at": e.created_at.isoformat(),
            }
            for e in tx.ledger_entries
        ],
    }


def execute_deposit(
    db: DbSession,
    user: User,
    account_id: uuid.UUID,
    amount_paise: int,
    idempotency_key: str,
    description: str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Execute a balanced double-entry deposit into a customer account."""
    if amount_paise <= 0:
        raise InvalidAmountError("Deposit amount must be a positive integer greater than zero")

    # 1. Idempotency Check & Reservation
    request_payload = {
        "action": "deposit",
        "account_id": str(account_id),
        "amount_paise": amount_paise,
        "description": description,
    }
    req_hash = compute_request_hash(request_payload)
    idemp_record, is_cached = check_or_reserve_idempotency_key(
        db=db,
        user_id=user.id,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
    )
    if is_cached:
        assert idemp_record.response_body is not None
        return json.loads(idemp_record.response_body)

    try:
        # 2. Authorization Check (requires OPERATE permission on destination account)
        dest_account = db.get(Account, account_id)
        if dest_account is None:
            raise AccountNotFoundError(f"Account {account_id} not found")

        membership = get_account_membership(db, user_id=user.id, account_id=account_id)
        check_account_permission(user, dest_account, membership, AccountAction.OPERATE)

        # 3. Retrieve system clearing account and acquire row locks in deterministic order
        clearing_acc = get_or_create_system_clearing_account(db)
        locked_clearing, locked_dest = _lock_accounts_in_order(db, clearing_acc.id, dest_account.id)

        # Re-verify account status under lock
        if locked_dest.status != AccountStatus.ACTIVE.value:
            raise AccountStatusError(f"Account '{locked_dest.id}' is {locked_dest.status.lower()} and cannot accept deposits")

        # 4. Post balanced double-entry transaction (Debit clearing, Credit destination)
        reference = f"DEP-{idempotency_key[:32]}"
        tx = post_ledger_transaction(
            db=db,
            transaction_type=TransactionType.DEPOSIT,
            amount_paise=amount_paise,
            debit_account=locked_clearing,
            credit_account=locked_dest,
            reference=reference,
            description=description,
            initiated_by=user.id,
            currency=locked_dest.currency,
        )

        # 5. Audit Logging
        record_audit_event(
            db=db,
            action="TRANSACTION_DEPOSIT",
            entity_type="Transaction",
            entity_id=tx.id,
            actor_user_id=user.id,
            metadata={
                "reference": tx.reference,
                "account_id": str(locked_dest.id),
                "amount_paise": amount_paise,
            },
            ip_address=ip_address,
        )

        # 6. Save Idempotency response and commit atomically
        response_data = _build_transaction_response(tx)
        save_idempotency_response(db, idemp_record, status_code=200, response_body=response_data)
        db.commit()
        return response_data

    except Exception:
        db.rollback()
        raise


def execute_withdrawal(
    db: DbSession,
    user: User,
    account_id: uuid.UUID,
    amount_paise: int,
    idempotency_key: str,
    description: str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Execute a balanced double-entry withdrawal from a customer account."""
    if amount_paise <= 0:
        raise InvalidAmountError("Withdrawal amount must be a positive integer greater than zero")

    # 1. Idempotency Check & Reservation
    request_payload = {
        "action": "withdrawal",
        "account_id": str(account_id),
        "amount_paise": amount_paise,
        "description": description,
    }
    req_hash = compute_request_hash(request_payload)
    idemp_record, is_cached = check_or_reserve_idempotency_key(
        db=db,
        user_id=user.id,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
    )
    if is_cached:
        assert idemp_record.response_body is not None
        return json.loads(idemp_record.response_body)

    try:
        # 2. Authorization Check (requires OPERATE permission on source account)
        source_account = db.get(Account, account_id)
        if source_account is None:
            raise AccountNotFoundError(f"Account {account_id} not found")

        membership = get_account_membership(db, user_id=user.id, account_id=account_id)
        check_account_permission(user, source_account, membership, AccountAction.OPERATE)

        # 3. Retrieve system clearing account and acquire row locks in deterministic order
        clearing_acc = get_or_create_system_clearing_account(db)
        locked_source, locked_clearing = _lock_accounts_in_order(db, source_account.id, clearing_acc.id)

        # Re-verify account status and balance under lock
        if locked_source.status != AccountStatus.ACTIVE.value:
            raise AccountStatusError(f"Account '{locked_source.id}' is {locked_source.status.lower()} and cannot process withdrawals")

        if locked_source.balance < amount_paise:
            raise InsufficientFundsError(
                f"Insufficient funds: account balance ({locked_source.balance} paise) is less than requested withdrawal ({amount_paise} paise)"
            )

        # 4. Post balanced double-entry transaction (Debit source, Credit clearing)
        reference = f"WTH-{idempotency_key[:32]}"
        tx = post_ledger_transaction(
            db=db,
            transaction_type=TransactionType.WITHDRAWAL,
            amount_paise=amount_paise,
            debit_account=locked_source,
            credit_account=locked_clearing,
            reference=reference,
            description=description,
            initiated_by=user.id,
            currency=locked_source.currency,
        )

        # 5. Audit Logging
        record_audit_event(
            db=db,
            action="TRANSACTION_WITHDRAWAL",
            entity_type="Transaction",
            entity_id=tx.id,
            actor_user_id=user.id,
            metadata={
                "reference": tx.reference,
                "account_id": str(locked_source.id),
                "amount_paise": amount_paise,
            },
            ip_address=ip_address,
        )

        # 6. Save Idempotency response and commit atomically
        response_data = _build_transaction_response(tx)
        save_idempotency_response(db, idemp_record, status_code=200, response_body=response_data)
        db.commit()
        return response_data

    except Exception:
        db.rollback()
        raise


def execute_transfer(
    db: DbSession,
    user: User,
    source_account_id: uuid.UUID,
    destination_account_id: uuid.UUID,
    amount_paise: int,
    idempotency_key: str,
    description: str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Execute a balanced double-entry peer-to-peer transfer between two accounts."""
    if amount_paise <= 0:
        raise InvalidAmountError("Transfer amount must be a positive integer greater than zero")

    if source_account_id == destination_account_id:
        raise SameAccountTransferError("Cannot transfer money to the same account")

    # 1. Idempotency Check & Reservation
    request_payload = {
        "action": "transfer",
        "source_account_id": str(source_account_id),
        "destination_account_id": str(destination_account_id),
        "amount_paise": amount_paise,
        "description": description,
    }
    req_hash = compute_request_hash(request_payload)
    idemp_record, is_cached = check_or_reserve_idempotency_key(
        db=db,
        user_id=user.id,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
    )
    if is_cached:
        assert idemp_record.response_body is not None
        return json.loads(idemp_record.response_body)

    try:
        # 2. Authorization Check on source account (initiator must have OPERATE permission)
        source_account = db.get(Account, source_account_id)
        if source_account is None:
            raise AccountNotFoundError(f"Source account {source_account_id} not found")

        # Verify destination account exists
        dest_account = db.get(Account, destination_account_id)
        if dest_account is None:
            raise AccountNotFoundError(f"Destination account {destination_account_id} not found")

        # Prohibit transfers involving the system clearing account (use deposits/withdrawals instead)
        if source_account.account_number == SYSTEM_CLEARING_ACCOUNT_NUMBER:
            raise ClearingAccountTransferError("System clearing account cannot be used as transfer source")
        if dest_account.account_number == SYSTEM_CLEARING_ACCOUNT_NUMBER:
            raise ClearingAccountTransferError("System clearing account cannot be targeted by peer-to-peer transfers")

        membership = get_account_membership(db, user_id=user.id, account_id=source_account_id)
        check_account_permission(user, source_account, membership, AccountAction.OPERATE)

        # 3. Acquire row locks in sorted UUID order to prevent deadlocks
        locked_source, locked_dest = _lock_accounts_in_order(db, source_account_id, destination_account_id)

        # Re-verify account statuses under lock
        if locked_source.status != AccountStatus.ACTIVE.value:
            raise AccountStatusError(f"Source account '{locked_source.id}' is {locked_source.status.lower()} and cannot transfer funds")
        if locked_dest.status != AccountStatus.ACTIVE.value:
            raise AccountStatusError(f"Destination account '{locked_dest.id}' is {locked_dest.status.lower()} and cannot receive funds")

        # Verify currency compatibility
        if locked_source.currency != locked_dest.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: source={locked_source.currency}, dest={locked_dest.currency}"
            )

        # Verify balance
        if locked_source.balance < amount_paise:
            raise InsufficientFundsError(
                f"Insufficient funds: source balance ({locked_source.balance} paise) is less than transfer amount ({amount_paise} paise)"
            )

        # 4. Post balanced double-entry transaction (Debit source, Credit destination)
        reference = f"TRF-{idempotency_key[:32]}"
        tx = post_ledger_transaction(
            db=db,
            transaction_type=TransactionType.TRANSFER,
            amount_paise=amount_paise,
            debit_account=locked_source,
            credit_account=locked_dest,
            reference=reference,
            description=description,
            initiated_by=user.id,
            currency=locked_source.currency,
        )

        # 5. Audit Logging
        record_audit_event(
            db=db,
            action="TRANSACTION_TRANSFER",
            entity_type="Transaction",
            entity_id=tx.id,
            actor_user_id=user.id,
            metadata={
                "reference": tx.reference,
                "source_account_id": str(locked_source.id),
                "destination_account_id": str(locked_dest.id),
                "amount_paise": amount_paise,
            },
            ip_address=ip_address,
        )

        # 6. Save Idempotency response and commit atomically
        response_data = _build_transaction_response(tx)
        save_idempotency_response(db, idemp_record, status_code=200, response_body=response_data)
        db.commit()
        return response_data

    except Exception:
        db.rollback()
        raise


def get_transaction_by_id(
    db: DbSession,
    user: User,
    transaction_id: uuid.UUID,
) -> Transaction:
    """Retrieve transaction details if user has active membership in at least one involved account.

    Enforces PROMPT-030 authorization policy:
    - Inactive users are rejected immediately with InactiveUserError.
    - All users (including ADMIN and AUDITOR) require active membership in at least one involved account.
    - Non-members receive AccountNotFoundError (HTTP 404 anti-IDOR), preventing transaction existence disclosure.
    """
    if not user.is_active:
        raise InactiveUserError("User account is inactive")

    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise AccountNotFoundError(f"Transaction {transaction_id} not found")

    # Verify user has membership in at least one involved customer account
    account_ids = {entry.account_id for entry in tx.ledger_entries}
    user_memberships = db.scalars(
        select(AccountMembership).where(
            AccountMembership.user_id == user.id,
            AccountMembership.account_id.in_(account_ids),
        )
    ).all()

    if not user_memberships:
        raise AccountNotFoundError("Transaction not found or access denied")

    return tx


def get_account_statement(
    db: DbSession,
    user: User,
    account_id: uuid.UUID,
) -> AccountStatementResponse:
    """Generate a chronological statement of all double-entry ledger postings for an account."""
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"Account {account_id} not found")

    # Verify user has read access
    membership = get_account_membership(db, user_id=user.id, account_id=account_id)
    check_account_permission(user, account, membership, AccountAction.READ)

    stmt = (
        select(LedgerEntry, Transaction)
        .join(Transaction, LedgerEntry.transaction_id == Transaction.id)
        .where(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.created_at.asc(), LedgerEntry.id.asc())
    )
    rows = db.execute(stmt).all()

    statement_entries = [
        AccountStatementItem(
            id=entry.id,
            transaction_id=tx.id,
            reference=tx.reference,
            transaction_type=tx.transaction_type,
            entry_type=entry.entry_type,
            amount_paise=entry.amount_paise,
            description=tx.description,
            created_at=entry.created_at,
        )
        for entry, tx in rows
    ]

    return AccountStatementResponse(
        account_id=account.id,
        account_number=account.account_number,
        currency=account.currency,
        balance_paise=account.balance,
        entries=statement_entries,
    )
