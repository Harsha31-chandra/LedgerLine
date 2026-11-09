"""
Financial transaction API routes for LedgerLine.

Provides:
- POST /transactions/deposit: Balanced double-entry deposit into an account.
- POST /transactions/withdraw: Balanced double-entry withdrawal from an account.
- POST /transactions/transfer: Balanced double-entry peer-to-peer transfer.
- GET /transactions/{transaction_id}: Retrieve transaction details.
- GET /accounts/{account_id}/statement: Chronological ledger statements for an account.
"""

import secrets
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session as DbSession

from backend.app.api.deps import get_current_user, get_db
from backend.app.core.exceptions import (
    AccountNotFoundError,
    AccountStatusError,
    AuditorReadOnlyViolationError,
    ClearingAccountTransferError,
    CurrencyMismatchError,
    IdempotencyCollisionError,
    IdempotencyInFlightError,
    InactiveUserError,
    InsufficientFundsError,
    InsufficientMembershipRoleError,
    InvalidAmountError,
    SameAccountTransferError,
)
from backend.app.models.transaction import Transaction
from backend.app.models.user import User
from backend.app.schemas.transaction import (
    AccountStatementResponse,
    DepositRequest,
    TransactionResponse,
    TransferRequest,
    WithdrawalRequest,
)
from backend.app.services.transaction_service import (
    execute_deposit,
    execute_transfer,
    execute_withdrawal,
    get_account_statement,
    get_transaction_by_id,
)

router = APIRouter(tags=["transactions"])


def _resolve_idempotency_key(key: str | None) -> str:
    """Resolve client-provided idempotency key or generate high-entropy fallback."""
    if key and key.strip():
        return key.strip()
    return f"auto-{secrets.token_hex(16)}"


@router.post(
    "/transactions/deposit",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Deposit funds into an account",
)
def deposit(
    request: Request,
    payload: DepositRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[DbSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    """Deposit money into a designated customer account.

    Requires OPERATE permission on the destination account. Idempotent.
    """
    client_ip = request.client.host if request.client else None
    resolved_key = _resolve_idempotency_key(idempotency_key)

    try:
        return execute_deposit(
            db=db,
            user=current_user,
            account_id=payload.account_id,
            amount_paise=payload.amount_paise,
            idempotency_key=resolved_key,
            description=payload.description,
            ip_address=client_ip,
        )
    except AccountNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    except AccountStatusError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except AuditorReadOnlyViolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditor role is restricted to read-only access",
        )
    except InsufficientMembershipRoleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this account action",
        )
    except InactiveUserError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
    except InvalidAmountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IdempotencyCollisionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except IdempotencyInFlightError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/transactions/withdraw",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Withdraw funds from an account",
)
def withdraw(
    request: Request,
    payload: WithdrawalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[DbSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    """Withdraw money from a customer account.

    Requires OPERATE permission on the source account and sufficient balance. Idempotent.
    """
    client_ip = request.client.host if request.client else None
    resolved_key = _resolve_idempotency_key(idempotency_key)

    try:
        return execute_withdrawal(
            db=db,
            user=current_user,
            account_id=payload.account_id,
            amount_paise=payload.amount_paise,
            idempotency_key=resolved_key,
            description=payload.description,
            ip_address=client_ip,
        )
    except AccountNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    except AccountStatusError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except AuditorReadOnlyViolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditor role is restricted to read-only access",
        )
    except InsufficientMembershipRoleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this account action",
        )
    except InactiveUserError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
    except InsufficientFundsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InvalidAmountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IdempotencyCollisionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except IdempotencyInFlightError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/transactions/transfer",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Transfer funds between two accounts",
)
def transfer(
    request: Request,
    payload: TransferRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[DbSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    """Transfer funds from a source account to a destination account.

    Requires OPERATE permission on source account. Protected by row locking in deterministic order. Idempotent.
    """
    client_ip = request.client.host if request.client else None
    resolved_key = _resolve_idempotency_key(idempotency_key)

    try:
        return execute_transfer(
            db=db,
            user=current_user,
            source_account_id=payload.source_account_id,
            destination_account_id=payload.destination_account_id,
            amount_paise=payload.amount_paise,
            idempotency_key=resolved_key,
            description=payload.description,
            ip_address=client_ip,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except AccountStatusError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except AuditorReadOnlyViolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditor role is restricted to read-only access",
        )
    except InsufficientMembershipRoleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this account action",
        )
    except InactiveUserError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
    except SameAccountTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ClearingAccountTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InsufficientFundsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InvalidAmountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except CurrencyMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IdempotencyCollisionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except IdempotencyInFlightError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve transaction details",
)
def get_transaction(
    transaction_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[DbSession, Depends(get_db)],
) -> Transaction:
    """Retrieve transaction details by UUID for authorized users."""
    try:
        return get_transaction_by_id(db=db, user=current_user, transaction_id=transaction_id)
    except AccountNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    except InactiveUserError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/accounts/{account_id}/statement",
    response_model=AccountStatementResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve chronological account statement",
)
def get_statement(
    account_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[DbSession, Depends(get_db)],
) -> AccountStatementResponse:
    """Retrieve full chronological double-entry statement for an authorized account."""
    try:
        return get_account_statement(db=db, user=current_user, account_id=account_id)
    except AccountNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    except InsufficientMembershipRoleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this account action",
        )
    except InactiveUserError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
