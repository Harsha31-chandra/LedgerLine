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

__all__ = ["SENSITIVE_METADATA_KEYS", "record_audit_event"]

# Comprehensive blocklist of credential and authentication-related metadata keys
SENSITIVE_METADATA_KEYS: frozenset[str] = frozenset({
    "password",
    "token",
    "raw_token",
    "access_token",
    "refresh_token",
    "password_hash",
    "token_hash",
    "authorization",
    "cookie",
    "secret",
    "session_secret",
    "client_secret",
    "private_key",
    "api_key",
    "credentials",
})


def _sanitize_metadata(data: Any, forbidden_keys: frozenset[str]) -> Any:
    """Recursively scrub forbidden sensitive keys from dictionary and list structures.

    Normalizes keys via strip().lower().

    LIMITATION NOTE:
    Key-based sanitization strictly prevents known credential dictionary keys from being
    persisted. It cannot guarantee removal of secrets accidentally embedded inside
    unstructured free-form text values (e.g. error strings or description fields).
    """
    if isinstance(data, dict):
        return {
            k: _sanitize_metadata(v, forbidden_keys)
            for k, v in data.items()
            if (k.strip().lower() if isinstance(k, str) else str(k).lower()) not in forbidden_keys
        }
    if isinstance(data, list):
        return [_sanitize_metadata(item, forbidden_keys) for item in data]
    return data


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
        clean_metadata = _sanitize_metadata(metadata, SENSITIVE_METADATA_KEYS)

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
