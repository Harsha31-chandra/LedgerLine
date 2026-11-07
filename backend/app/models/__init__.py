"""
SQLAlchemy models registration for LedgerLine.

Importing this package registers all eight models on Base.metadata:
1. User (users table)
2. Session (sessions table)
3. Account (accounts table)
4. AccountMembership (account_memberships table)
5. Transaction (transactions table)
6. LedgerEntry (ledger_entries table)
7. IdempotencyRecord (idempotency_records table)
8. AuditEvent (audit_events table)
"""

from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.audit_event import AuditEvent
from backend.app.models.base import Base
from backend.app.models.idempotency import IdempotencyRecord
from backend.app.models.ledger_entry import EntryType, LedgerEntry
from backend.app.models.session import Session
from backend.app.models.transaction import Transaction, TransactionStatus, TransactionType
from backend.app.models.user import User, UserRole

__all__ = [
    "Base",
    "User",
    "UserRole",
    "Session",
    "Account",
    "AccountStatus",
    "AccountMembership",
    "MembershipRole",
    "Transaction",
    "TransactionType",
    "TransactionStatus",
    "LedgerEntry",
    "EntryType",
    "IdempotencyRecord",
    "AuditEvent",
]
