"""
Administrative API routes for LedgerLine.

Provides:
- GET /admin/accounts: Administrative account registry listing all system accounts.
  Protected by require_admin dependency. Returns AccountResponse (excludes private
  statements, ledger journals, and operational membership tokens).
- GET /admin/stats: System-wide summary statistics (Admin-only).
- GET /admin/users: System users list with membership count (Admin-only).
- POST /admin/memberships: Assign or modify account membership (Admin-only).
- GET /admin/audit-logs: Audit event trail (Admin and Auditor).
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from backend.app.api.deps import get_db, require_admin, require_global_role
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership
from backend.app.models.audit_event import AuditEvent
from backend.app.models.transaction import Transaction
from backend.app.models.user import User, UserRole
from backend.app.schemas.account import AccountResponse
from backend.app.schemas.admin import (
    AdminStatsResponse,
    AdminUserResponse,
    AssignMembershipRequest,
)
from backend.app.schemas.audit import AuditEventResponse
from backend.app.services.account_service import (
    SYSTEM_CLEARING_ACCOUNT_NUMBER,
    assign_account_membership,
    list_all_accounts,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/accounts",
    response_model=list[AccountResponse],
    status_code=status.HTTP_200_OK,
    summary="List all system accounts for administrative oversight (Admin-only)",
)
def list_system_accounts(
    admin_user: Annotated[User, Depends(require_admin)],
    db: Annotated[DbSession, Depends(get_db)],
) -> list[AccountResponse]:
    """Return all accounts in the system for administrative registry oversight.

    Enforces:
    - Restricted strictly to global UserRole.ADMIN principals.
    - Excludes internal SYSTEM_CLEARING account to prevent exposure as an ordinary account.
    - Does not grant account-level operational permissions (deposit/withdraw/transfer).
    - Does not disclose private transaction histories or ledger statement lines.
    """
    accounts = list_all_accounts(db=db, admin_user=admin_user)
    return [AccountResponse.model_validate(acc) for acc in accounts]


@router.get(
    "/stats",
    response_model=AdminStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve system-wide summary metrics (Admin-only)",
)
def get_system_stats(
    admin_user: Annotated[User, Depends(require_admin)],
    db: Annotated[DbSession, Depends(get_db)],
) -> AdminStatsResponse:
    """Compute aggregate system metrics across users, accounts, balances, and transactions."""
    total_users = db.scalar(select(func.count(User.id))) or 0
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

    return AdminStatsResponse(
        total_users=total_users,
        total_accounts=total_accounts,
        active_accounts=active_accounts,
        frozen_accounts=frozen_accounts,
        closed_accounts=closed_accounts,
        total_portfolio_balance_paise=int(total_balance),
        total_transactions=total_txns,
    )


@router.get(
    "/users",
    response_model=list[AdminUserResponse],
    status_code=status.HTTP_200_OK,
    summary="List all users with their roles and membership metrics (Admin-only)",
)
def list_system_users(
    admin_user: Annotated[User, Depends(require_admin)],
    db: Annotated[DbSession, Depends(get_db)],
) -> list[AdminUserResponse]:
    """Retrieve all system users along with active account membership counts."""
    stmt = (
        select(User, func.count(AccountMembership.id).label("account_count"))
        .outerjoin(AccountMembership, User.id == AccountMembership.user_id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
    )
    results = db.execute(stmt).all()
    user_responses = []
    for user_obj, count in results:
        user_responses.append(
            AdminUserResponse(
                id=user_obj.id,
                email=user_obj.email,
                full_name=user_obj.full_name,
                role=user_obj.role,
                is_active=user_obj.is_active,
                created_at=user_obj.created_at,
                account_count=count,
            )
        )
    return user_responses


@router.post(
    "/memberships",
    status_code=status.HTTP_200_OK,
    summary="Assign or update account membership for a user (Admin-only)",
)
def assign_membership(
    payload: AssignMembershipRequest,
    admin_user: Annotated[User, Depends(require_admin)],
    db: Annotated[DbSession, Depends(get_db)],
    request: Request,
) -> dict[str, str]:
    """Assign or update a user's membership role on a designated financial account."""
    ip = request.client.host if request.client else None
    membership = assign_account_membership(
        db=db,
        admin_user=admin_user,
        account_id=payload.account_id,
        user_id=payload.user_id,
        role=payload.role,
        ip_address=ip,
    )
    return {
        "message": f"Successfully assigned {membership.membership_role} role to user on account",
        "membership_role": membership.membership_role,
    }


@router.get(
    "/audit-logs",
    response_model=list[AuditEventResponse],
    status_code=status.HTTP_200_OK,
    summary="List system audit logs (Admin and Auditor)",
)
def list_audit_logs(
    current_user: Annotated[User, Depends(require_global_role(UserRole.ADMIN, UserRole.AUDITOR))],
    db: Annotated[DbSession, Depends(get_db)],
    action: str | None = Query(default=None, description="Optional action filter"),
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
