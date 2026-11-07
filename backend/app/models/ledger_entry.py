"""
LedgerEntry model representing immutable, append-only double-entry financial postings.
"""

from datetime import datetime, timezone
from enum import StrEnum
import uuid

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class EntryType(StrEnum):
    """Side of double-entry ledger posting."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerEntry(Base):
    """Authoritative financial record. Strictly append-only; never updated or deleted."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "amount_paise > 0",
            name="ck_ledger_entries_amount_paise_positive",
        ),
        CheckConstraint(
            "entry_type IN ('DEBIT', 'CREDIT')",
            name="ck_ledger_entries_type_valid",
        ),
        # Composite index for fast chronological statement queries by account
        Index(
            "ix_ledger_entries_account_created",
            "account_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entry_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )
    amount_paise: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )

    # Relationships
    transaction: Mapped["Transaction"] = relationship(
        "Transaction",
        back_populates="ledger_entries",
    )
    account: Mapped["Account"] = relationship(
        "Account",
        back_populates="ledger_entries",
    )

    def __repr__(self) -> str:
        return f"<LedgerEntry id={self.id} account_id={self.account_id} type={self.entry_type} amount_paise={self.amount_paise}>"
