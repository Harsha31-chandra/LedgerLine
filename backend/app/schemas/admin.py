"""
Administrative and oversight schemas for LedgerLine.
"""

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.account_membership import MembershipRole
from backend.app.models.user import UserRole


class AdminStatsResponse(BaseModel):
    """System-wide summary metrics for administrative oversight."""

    model_config = ConfigDict(extra="forbid")

    total_users: int
    total_accounts: int
    active_accounts: int
    frozen_accounts: int
    closed_accounts: int
    total_portfolio_balance_paise: int
    total_transactions: int


class AdminUserResponse(BaseModel):
    """User account details for administrative user management."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    account_count: int = 0


class AssignMembershipRequest(BaseModel):
    """Request to assign or modify a user's account membership role."""

    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    user_id: uuid.UUID
    role: MembershipRole
