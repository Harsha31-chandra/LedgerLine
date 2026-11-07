"""
Account model representing financial accounts and customer wallets.

CRITICAL FINANCIAL INVARIANT:
The `balance` column on this table stores integer paise as an operational performance cache (snapshot).
It MUST NEVER replace the authoritative double-entry ledger (`ledger_entries`) as the financial source of truth.
The true, auditable balance is always derived from posted ledger entries.
"""

from datetime import datetime, timezone
from enum import StrEnum
import uuid

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class AccountStatus(StrEnum):
    """Lifecycle status for financial accounts."""

    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class Account(Base):
    """Account entity representing customer wallets and system clearing accounts."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "balance >= 0",
            name="ck_accounts_balance_non_negative",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'FROZEN', 'CLOSED')",
            name="ck_accounts_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    account_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    account_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
    )
    balance: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AccountStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    memberships: Mapped[list["AccountMembership"]] = relationship(
        "AccountMembership",
        back_populates="account",
        cascade="all, delete-orphan",
    )
    # Financial history must NEVER cascade-delete
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="account",
    )

    def __repr__(self) -> str:
        return f"<Account id={self.id} number={self.account_number} balance_paise={self.balance}>"
