"""
Transaction model representing the business intent and lifecycle of a money movement.
"""

from datetime import datetime, timezone
from enum import StrEnum
import uuid

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class TransactionType(StrEnum):
    """Supported transaction operation kinds."""

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"


class TransactionStatus(StrEnum):
    """Lifecycle states of a financial transaction."""

    PENDING = "PENDING"
    POSTED = "POSTED"
    REJECTED = "REJECTED"


class Transaction(Base):
    """Logical business transaction header tracking intent, state, and audit references."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "amount_paise > 0",
            name="ck_transactions_amount_paise_positive",
        ),
        CheckConstraint(
            "transaction_type IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER')",
            name="ck_transactions_type_valid",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'POSTED', 'REJECTED')",
            name="ck_transactions_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    reference: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    transaction_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TransactionStatus.PENDING,
    )
    amount_paise: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
    )
    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    initiator: Mapped["User | None"] = relationship(
        "User",
        back_populates="initiated_transactions",
    )
    # Financial history must NEVER cascade-delete
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry",
        back_populates="transaction",
    )

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} ref={self.reference} type={self.transaction_type} status={self.status}>"
