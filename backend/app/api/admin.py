"""
Administrative API routes for LedgerLine.

Provides:
- GET /admin/accounts: Administrative account registry listing all system accounts.
  Protected by require_admin dependency. Returns AccountResponse (excludes private
  statements, ledger journals, and operational membership tokens).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session as DbSession

from backend.app.api.deps import get_db, require_admin
from backend.app.models.user import User
from backend.app.schemas.account import AccountResponse
from backend.app.services.account_service import list_all_accounts

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
