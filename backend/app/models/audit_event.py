"""
AuditEvent model representing append-only audit trail for business and security operations.
"""

from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class AuditEvent(Base):
    """Tamper-evident, append-only security and operational audit trail."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "ix_audit_events_action_created",
            "action",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    entity_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    # The database column is named "metadata", mapped to Python attribute "event_metadata"
    # to avoid conflict with SQLAlchemy's reserved DeclarativeBase.metadata attribute.
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )

    # Relationships
    actor: Mapped["User | None"] = relationship(
        "User",
        back_populates="audit_events",
    )

    def __repr__(self) -> str:
        return f"<AuditEvent id={self.id} action={self.action} actor={self.actor_user_id}>"
