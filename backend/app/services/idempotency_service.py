"""
Idempotency service for LedgerLine financial transactions.

Provides:
- User-scoped idempotency key reservation and conflict detection.
- Canonical SHA-256 request payload hashing.
- Safe replay of cached financial transaction results.
- Protection against concurrent duplicate requests and parameter tampering.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from backend.app.core.exceptions import (
    IdempotencyCollisionError,
    IdempotencyInFlightError,
)
from backend.app.models.idempotency import IdempotencyRecord

__all__ = [
    "check_or_reserve_idempotency_key",
    "compute_request_hash",
    "save_idempotency_response",
]


def compute_request_hash(payload: Any) -> str:
    """Compute standard SHA-256 hash of a canonically serialized request payload.

    Args:
        payload: Dictionary or JSON-serializable structure.

    Returns:
        64-character lowercase hexadecimal SHA-256 digest.
    """
    if isinstance(payload, dict):
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    else:
        canonical_json = str(payload)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _is_expired(expires_at: datetime, now: datetime) -> bool:
    """Check if an expiration timestamp has passed, normalizing naive timestamps to UTC."""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def check_or_reserve_idempotency_key(
    db: DbSession,
    user_id: uuid.UUID,
    idempotency_key: str,
    request_hash: str,
    ttl_hours: int = 24,
) -> tuple[IdempotencyRecord, bool]:
    """Check an existing idempotency record or reserve the key for the current operation.

    Enforces:
    - Time-to-live (TTL) expiration: expired records are reclaimed in-place.
    - Safe cached replay for unexpired completed records with identical request hash.
    - Parameter tampering collision detection for unexpired records with differing request hash.
    - In-flight concurrency protection for active unexpired operations.
    - Atomic savepoints to handle concurrent insert races cleanly without session invalidation.

    Args:
        db: Active SQLAlchemy database session.
        user_id: Authenticated user UUID.
        idempotency_key: Client-provided idempotency key string.
        request_hash: SHA-256 hash of the canonical request parameters.
        ttl_hours: Time-to-live in hours before idempotency key expires.

    Returns:
        Tuple of (IdempotencyRecord, is_cached: bool). If is_cached is True, the operation
        has already executed and the cached response should be returned.

    Raises:
        IdempotencyCollisionError: If unexpired key was previously used with different parameters.
        IdempotencyInFlightError: If a concurrent request is currently processing this key.
    """
    stmt = (
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )
    existing = db.scalars(stmt).first()

    now = datetime.now(timezone.utc)

    if existing is not None:
        # Check if record has expired
        if _is_expired(existing.expires_at, now):
            # Key has expired: reclaim and reset for fresh execution
            existing.request_hash = request_hash
            existing.response_status = None
            existing.response_body = None
            existing.expires_at = now + timedelta(hours=ttl_hours)
            db.add(existing)
            db.flush()
            return existing, False

        # Key is unexpired: check if previous execution finished
        if existing.response_status is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyCollisionError(
                    f"Idempotency key '{idempotency_key}' was previously used with different parameters."
                )
            return existing, True

        # Key is unexpired and response_status is None -> active execution in flight
        raise IdempotencyInFlightError(
            f"A request with idempotency key '{idempotency_key}' is currently in progress."
        )

    # Reserve the key atomically within a savepoint to handle concurrent insert races
    try:
        with db.begin_nested():
            record = IdempotencyRecord(
                user_id=user_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response_status=None,
                response_body=None,
                expires_at=now + timedelta(hours=ttl_hours),
            )
            db.add(record)
            db.flush()
        return record, False
    except IntegrityError:
        # Concurrent worker inserted the key. Re-fetch and evaluate state.
        stmt = (
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        concurrent_existing = db.scalars(stmt).first()
        if concurrent_existing is not None:
            if not _is_expired(concurrent_existing.expires_at, now):
                if concurrent_existing.response_status is not None:
                    if concurrent_existing.request_hash != request_hash:
                        raise IdempotencyCollisionError(
                            f"Idempotency key '{idempotency_key}' was previously used with different parameters."
                        )
                    return concurrent_existing, True
        raise IdempotencyInFlightError(
            f"A concurrent request with idempotency key '{idempotency_key}' was just initiated."
        )


def save_idempotency_response(
    db: DbSession,
    record: IdempotencyRecord,
    status_code: int,
    response_body: dict[str, Any] | str,
) -> None:
    """Store the final response payload and status on an active idempotency record.

    Args:
        db: Active SQLAlchemy database session.
        record: Reserved IdempotencyRecord instance.
        status_code: HTTP status code of the response.
        response_body: Response dictionary or JSON string.
    """
    if isinstance(response_body, dict):
        serialized_body = json.dumps(response_body, default=str)
    else:
        serialized_body = str(response_body)

    record.response_status = status_code
    record.response_body = serialized_body
    db.add(record)
