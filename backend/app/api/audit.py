"""
Auditor oversight API routes for LedgerLine.

Provides:
- GET /audit/overview: Global system financial metrics (Auditor and Admin).
- GET /audit/accounts: Global account inventory read-only inspection (Auditor and Admin).
- GET /audit/transactions: Global transaction journal and ledger entries (Auditor and Admin).
- GET /audit/logs: Complete audit trail log (Auditor and Admin).

All routes enforce strict read-only access and reject unauthorized roles (HOLDER -> 403).
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession, selectinload

from backend.app.api.deps import get_db, require_global_role
from backend.app.models.account import Account, AccountStatus
from backend.app.models.audit_event import AuditEvent
from backend.app.models.ledger_entry import LedgerEntry
from backend.app.models.transaction import Transaction
from backend.app.models.user import User, UserRole
from backend.app.schemas.account import AccountResponse
from backend.app.schemas.audit import AuditEventResponse, GlobalOverviewResponse
from backend.app.schemas.transaction import TransactionResponse
from backend.app.services.account_service import SYSTEM_CLEARING_ACCOUNT_NUMBER

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "/overview",
    response_model=GlobalOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve global financial and ledger overview (Auditor & Admin)",
)
def get_global_overview(
    auditor: Annotated[User, Depends(require_global_role(UserRole.AUDITOR, UserRole.ADMIN))],
    db: Annotated[DbSession, Depends(get_db)],
) -> GlobalOverviewResponse:
    """Return high-level portfolio metrics and ledger totals for system-wide oversight."""
    total_accounts = (
        db.scalar(
            select(func.count(Account.id)).where(
                Account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER
            )
        )
        or 0
    )
    active_accounts = (
        db.scalar(
            select(func.count(Account.id)).where(
                Account.status == AccountStatus.ACTIVE,
                Account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER,
            )
        )
        or 0
    )
    frozen_accounts = (
        db.scalar(
            select(func.count(Account.id)).where(
                Account.status == AccountStatus.FROZEN,
                Account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER,
            )
        )
        or 0
    )
    closed_accounts = (
        db.scalar(
            select(func.count(Account.id)).where(
                Account.status == AccountStatus.CLOSED,
                Account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER,
            )
        )
        or 0
    )
    total_balance = (
        db.scalar(
            select(func.sum(Account.balance)).where(
                Account.status == AccountStatus.ACTIVE,
                Account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER,
            )
        )
        or 0
    )
    total_txns = db.scalar(select(func.count(Transaction.id))) or 0
    total_entries = db.scalar(select(func.count(LedgerEntry.id))) or 0

    return GlobalOverviewResponse(
        total_accounts=total_accounts,
        active_accounts=active_accounts,
        frozen_accounts=frozen_accounts,
        closed_accounts=closed_accounts,
        total_portfolio_balance_paise=int(total_balance),
        total_transactions=total_txns,
        total_ledger_entries=total_entries,
    )


@router.get(
    "/accounts",
    response_model=list[AccountResponse],
    status_code=status.HTTP_200_OK,
    summary="List all system accounts for read-only audit inspection (Auditor & Admin)",
)
def list_audit_accounts(
    auditor: Annotated[User, Depends(require_global_role(UserRole.AUDITOR, UserRole.ADMIN))],
    db: Annotated[DbSession, Depends(get_db)],
) -> list[AccountResponse]:
    """Return read-only list of all non-clearing customer accounts."""
    stmt = (
        select(Account)
        .where(Account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER)
        .order_by(Account.created_at.desc())
    )
    accounts = db.scalars(stmt).all()
    return [AccountResponse.model_validate(acc) for acc in accounts]


@router.get(
    "/transactions",
    response_model=list[TransactionResponse],
    status_code=status.HTTP_200_OK,
    summary="Inspect global transactions journal with balanced ledger entries (Auditor & Admin)",
)
def list_audit_transactions(
    auditor: Annotated[User, Depends(require_global_role(UserRole.AUDITOR, UserRole.ADMIN))],
    db: Annotated[DbSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TransactionResponse]:
    """Retrieve global transaction journal records with eagerly loaded ledger entries."""
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.ledger_entries))
        .order_by(Transaction.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    transactions = db.scalars(stmt).all()
    return [TransactionResponse.model_validate(tx) for tx in transactions]


@router.get(
    "/logs",
    response_model=list[AuditEventResponse],
    status_code=status.HTTP_200_OK,
    summary="Inspect tamper-evident audit events (Auditor & Admin)",
)
def list_audit_events(
    auditor: Annotated[User, Depends(require_global_role(UserRole.AUDITOR, UserRole.ADMIN))],
    db: Annotated[DbSession, Depends(get_db)],
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEventResponse]:
    """Retrieve tamper-evident audit logs with actor and metadata inspection."""
    stmt = (
        select(
            AuditEvent,
            User.email.label("actor_email"),
            User.full_name.label("actor_name"),
        )
        .outerjoin(User, AuditEvent.actor_user_id == User.id)
        .order_by(AuditEvent.created_at.desc())
    )
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    stmt = stmt.offset(offset).limit(limit)

    results = db.execute(stmt).all()
    events = []
    for event, actor_email, actor_name in results:
        events.append(
            AuditEventResponse(
                id=event.id,
                actor_user_id=event.actor_user_id,
                actor_email=actor_email,
                actor_name=actor_name,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                event_metadata=event.event_metadata,
                created_at=event.created_at,
                ip_address=event.ip_address,
            )
        )
    return events
