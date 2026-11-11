"""
Audit event and system oversight schemas for LedgerLine.
"""

from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    """Audit log entry representation."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_email: str | None = None
    actor_name: str | None = None
    action: str
    entity_type: str
    entity_id: str | None
    event_metadata: dict[str, Any] | None
    created_at: datetime
    ip_address: str | None


class GlobalOverviewResponse(BaseModel):
    """Global financial overview for read-only audit inspection."""

    model_config = ConfigDict(extra="forbid")

    total_accounts: int
    active_accounts: int
    frozen_accounts: int
    closed_accounts: int
    total_portfolio_balance_paise: int
    total_transactions: int
    total_ledger_entries: int
