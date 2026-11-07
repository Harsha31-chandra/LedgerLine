"""
AccountMembership model mapping users to accounts with specific permissions.
Enforces per-account authorization and prevents Broken Object Level Authorization (BOLA/IDOR).
"""

from datetime import datetime, timezone
from enum import StrEnum
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class MembershipRole(StrEnum):
    """Account-level entitlement roles."""

    OWNER = "OWNER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class AccountMembership(Base):
    """Junction entity defining a user's role and access rights to an account."""

    __tablename__ = "account_memberships"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "account_id",
            name="uq_account_memberships_user_account",
        ),
        CheckConstraint(
            "membership_role IN ('OWNER', 'OPERATOR', 'VIEWER')",
            name="ck_account_memberships_role_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MembershipRole.OWNER,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="memberships",
    )
    account: Mapped["Account"] = relationship(
        "Account",
        back_populates="memberships",
    )

    def __repr__(self) -> str:
        return f"<AccountMembership user_id={self.user_id} account_id={self.account_id} role={self.membership_role}>"
