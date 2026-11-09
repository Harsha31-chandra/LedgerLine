"""
Account and account membership schemas for LedgerLine.
"""

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.account import AccountStatus
from backend.app.models.account_membership import MembershipRole


class AccountBase(BaseModel):
    """Base schema for account attributes."""

    account_name: str = Field(..., min_length=1, max_length=100)
    currency: str = Field(default="INR", min_length=3, max_length=3)


class AccountCreateRequest(AccountBase):
    """Request schema for creating an account (Admin-only)."""

    model_config = ConfigDict(extra="forbid")

    owner_user_id: uuid.UUID | None = Field(
        default=None,
        description="Optional user ID to assign as initial account OWNER. If omitted, creator is assigned.",
    )


class AccountUpdateRequest(BaseModel):
    """Request schema for updating account metadata (Owner-only)."""

    model_config = ConfigDict(extra="forbid")

    account_name: str = Field(..., min_length=1, max_length=100)


class AccountStatusUpdateRequest(BaseModel):
    """Request schema for administrative account status transition (Admin-only)."""

    model_config = ConfigDict(extra="forbid")

    status: AccountStatus


class AccountResponse(AccountBase):
    """Public account details response schema."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    account_number: str
    balance: int
    status: AccountStatus
    created_at: datetime
    updated_at: datetime


class AccountMembershipResponse(BaseModel):
    """Account membership details response schema."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    account_id: uuid.UUID
    user_id: uuid.UUID
    membership_role: MembershipRole
    created_at: datetime


class AccountWithMembershipResponse(AccountResponse):
    """Account details paired with the authenticated user's membership role."""

    membership_role: MembershipRole
