"""
User model representing authenticated principals and their system roles.
"""

from datetime import datetime, timezone
from enum import StrEnum
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class UserRole(StrEnum):
    """System-level access roles for LedgerLine."""

    ADMIN = "ADMIN"
    HOLDER = "HOLDER"
    AUDITOR = "AUDITOR"


class User(Base):
    """User account entity with credentials and authorization role."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN', 'HOLDER', 'AUDITOR')",
            name="ck_users_role_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=UserRole.HOLDER,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
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

    # Relationships (string-based to prevent circular imports)
    sessions: Mapped[list["Session"]] = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    memberships: Mapped[list["AccountMembership"]] = relationship(
        "AccountMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    initiated_transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="initiator",
    )
    idempotency_records: Mapped[list["IdempotencyRecord"]] = relationship(
        "IdempotencyRecord",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        "AuditEvent",
        back_populates="actor",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
