"""
Audit service for recording security and business events in LedgerLine.

Provides:
- Append-only recording of audit events attached to the active database transaction.
- Explicit sanitization ensuring passwords, raw session tokens, or keys are never persisted in event metadata.
"""

from typing import Any
import uuid

from sqlalchemy.orm import Session as DbSession

from backend.app.models.audit_event import AuditEvent

__all__ = ["record_audit_event"]


def record_audit_event(
    db: DbSession,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    """Record an audit event within the active unit of work.

    Args:
        db: Active SQLAlchemy database session.
        action: Specific action performed (e.g. 'ACCOUNT_CREATED', 'TRANSACTION_TRANSFER').
        entity_type: The domain entity affected (e.g. 'Account', 'Transaction').
        entity_id: Identifier of the affected entity.
        actor_user_id: User UUID who initiated the action.
        metadata: Structured non-sensitive metadata dictionary.
        ip_address: Client IP address.

    Returns:
        The newly added AuditEvent instance.
    """
    clean_metadata: dict[str, Any] | None = None
    if metadata:
        # Sanitize sensitive fields if accidentally included
        forbidden_keys = {"password", "token", "raw_token", "password_hash", "token_hash"}
        clean_metadata = {k: v for k, v in metadata.items() if k.lower() not in forbidden_keys}

    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        event_metadata=clean_metadata,
        ip_address=ip_address,
    )
    db.add(event)
    return event
