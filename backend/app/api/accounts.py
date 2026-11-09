"""
Account management API routes for LedgerLine.

Provides:
- POST /accounts: Create account and assign initial OWNER (Admin-only).
- GET /accounts: List all accounts accessible to authenticated user.
- GET /accounts/{account_id}: Retrieve account details (scoped to authorized members).
- PATCH /accounts/{account_id}: Update account metadata (Owner-only).
- POST /accounts/{account_id}/status: Administrative freeze/close/activate (Admin-only).
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DbSession

from backend.app.api.deps import (
    get_current_user,
    get_db,
    require_account_manage,
    require_account_read,
    require_admin,
)
from backend.app.core.exceptions import (
    AccountNotFoundError,
    AccountStatusError,
    AuditorReadOnlyViolationError,
    InactiveUserError,
    InsufficientMembershipRoleError,
    InsufficientRoleError,
)
from backend.app.models.account import Account
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.user import User
from backend.app.schemas.account import (
    AccountCreateRequest,
    AccountResponse,
    AccountStatusUpdateRequest,
    AccountUpdateRequest,
    AccountWithMembershipResponse,
)
from backend.app.services.account_service import (
    change_account_status,
    create_account,
    list_user_accounts,
    update_account_details,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post(
    "",
    response_model=AccountWithMembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new financial account (Admin-only)",
)
def create_new_account(
    request: Request,
    payload: AccountCreateRequest,
    admin_user: Annotated[User, Depends(require_admin)],
    db: Annotated[DbSession, Depends(get_db)],
) -> AccountWithMembershipResponse:
    """Create a new account with an initial OWNER membership atomically.

    Requires UserRole.ADMIN. Designated owner_user_id is verified server-side.
    """
    client_ip = request.client.host if request.client else None
    try:
        account, membership = create_account(
            db=db,
            creator_user=admin_user,
            account_name=payload.account_name,
            currency=payload.currency,
            owner_user_id=payload.owner_user_id,
            ip_address=client_ip,
        )
        return AccountWithMembershipResponse(
            id=account.id,
            account_number=account.account_number,
            account_name=account.account_name,
            currency=account.currency,
            balance=account.balance,
            status=account.status,
            created_at=account.created_at,
            updated_at=account.updated_at,
            membership_role=MembershipRole(membership.membership_role),
        )
    except InactiveUserError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InsufficientRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "",
    response_model=list[AccountWithMembershipResponse],
    status_code=status.HTTP_200_OK,
    summary="List all accounts accessible to authenticated user",
)
def list_accounts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[DbSession, Depends(get_db)],
) -> list[AccountWithMembershipResponse]:
    """Return all accounts where the authenticated user has an active membership."""
    results = list_user_accounts(db=db, user=current_user)
    return [
        AccountWithMembershipResponse(
            id=acc.id,
            account_number=acc.account_number,
            account_name=acc.account_name,
            currency=acc.currency,
            balance=acc.balance,
            status=acc.status,
            created_at=acc.created_at,
            updated_at=acc.updated_at,
            membership_role=MembershipRole(role_str),
        )
        for acc, role_str in results
    ]


@router.get(
    "/{account_id}",
    response_model=AccountWithMembershipResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve account details by UUID",
)
def get_account(
    account_and_mem: Annotated[tuple[Account, AccountMembership], Depends(require_account_read)],
) -> AccountWithMembershipResponse:
    """Retrieve account details for an authorized member (returns 404 for unowned accounts)."""
    account, membership = account_and_mem
    return AccountWithMembershipResponse(
        id=account.id,
        account_number=account.account_number,
        account_name=account.account_name,
        currency=account.currency,
        balance=account.balance,
        status=account.status,
        created_at=account.created_at,
        updated_at=account.updated_at,
        membership_role=MembershipRole(membership.membership_role),
    )


@router.patch(
    "/{account_id}",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Update account metadata (Owner-only)",
)
def update_account(
    account_id: uuid.UUID,
    payload: AccountUpdateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[DbSession, Depends(get_db)],
    _auth_guard: Annotated[tuple[Account, AccountMembership], Depends(require_account_manage)],
) -> Account:
    """Update account name. Restricted strictly to users with OWNER membership."""
    client_ip = request.client.host if request.client else None
    try:
        return update_account_details(
            db=db,
            user=current_user,
            account_id=account_id,
            new_account_name=payload.account_name,
            ip_address=client_ip,
        )
    except AccountNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
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


@router.post(
    "/{account_id}/status",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Update account lifecycle status (Admin-only)",
)
def update_status(
    account_id: uuid.UUID,
    payload: AccountStatusUpdateRequest,
    request: Request,
    admin_user: Annotated[User, Depends(require_admin)],
    db: Annotated[DbSession, Depends(get_db)],
) -> Account:
    """Freeze, unfreeze, or close an account. Restricted to system administrators."""
    client_ip = request.client.host if request.client else None
    try:
        return change_account_status(
            db=db,
            admin_user=admin_user,
            account_id=account_id,
            new_status=payload.status,
            ip_address=client_ip,
        )
    except AccountNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    except AccountStatusError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InsufficientRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
