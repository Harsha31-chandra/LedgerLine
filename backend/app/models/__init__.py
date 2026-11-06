"""
SQLAlchemy models registration.

All eight models will be registered with SQLAlchemy metadata here:
1. User (users table)
2. Session (sessions table)
3. Account (accounts table)
4. AccountMembership (account_memberships table)
5. Transaction (transactions table)
6. LedgerEntry (ledger_entries table)
7. IdempotencyRecord (idempotency_records table)
8. AuditEvent (audit_events table)

Base is exposed for Alembic autogenerate and model inheritance.
"""

from backend.app.models.base import Base

# Each model will be imported and registered on Base.metadata as implemented:
# from backend.app.models.user import User
# from backend.app.models.session import Session
# from backend.app.models.account import Account
# from backend.app.models.account_membership import AccountMembership
# from backend.app.models.transaction import Transaction
# from backend.app.models.ledger_entry import LedgerEntry
# from backend.app.models.idempotency import IdempotencyRecord
# from backend.app.models.audit_event import AuditEvent

__all__ = [
    "Base",
]
