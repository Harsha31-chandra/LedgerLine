"""
Transaction and ledger entry schemas for LedgerLine financial operations.
"""

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.ledger_entry import EntryType
from backend.app.models.transaction import TransactionStatus, TransactionType


MAX_PAISE_AMOUNT = 9_223_372_036_854_775_807  # PostgreSQL signed 64-bit BigInteger maximum


class DepositRequest(BaseModel):
    """Payload for deposit into a destination account."""

    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    amount_paise: int = Field(
        ...,
        strict=True,
        gt=0,
        le=MAX_PAISE_AMOUNT,
        description="Deposit amount in minor integer paise (strictly positive integer, max 2^63-1)",
    )
    description: str | None = Field(default=None, max_length=255)


class WithdrawalRequest(BaseModel):
    """Payload for withdrawal from a source account."""

    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    amount_paise: int = Field(
        ...,
        strict=True,
        gt=0,
        le=MAX_PAISE_AMOUNT,
        description="Withdrawal amount in minor integer paise (strictly positive integer, max 2^63-1)",
    )
    description: str | None = Field(default=None, max_length=255)


class TransferRequest(BaseModel):
    """Payload for peer-to-peer transfer between two accounts."""

    model_config = ConfigDict(extra="forbid")

    source_account_id: uuid.UUID
    destination_account_id: uuid.UUID
    amount_paise: int = Field(
        ...,
        strict=True,
        gt=0,
        le=MAX_PAISE_AMOUNT,
        description="Transfer amount in minor integer paise (strictly positive integer, max 2^63-1)",
    )
    description: str | None = Field(default=None, max_length=255)


class LedgerEntryResponse(BaseModel):
    """Public view of an individual balanced ledger journal entry."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    transaction_id: uuid.UUID
    account_id: uuid.UUID
    entry_type: EntryType
    amount_paise: int
    created_at: datetime


class TransactionResponse(BaseModel):
    """Public view of a posted financial transaction and its balanced entries."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    reference: str
    transaction_type: TransactionType
    status: TransactionStatus
    amount_paise: int
    currency: str
    description: str | None
    initiated_by: uuid.UUID | None
    created_at: datetime
    ledger_entries: list[LedgerEntryResponse] = []


class AccountStatementItem(BaseModel):
    """Single chronological statement journal entry."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    transaction_id: uuid.UUID
    reference: str
    transaction_type: TransactionType
    entry_type: EntryType
    amount_paise: int
    description: str | None
    created_at: datetime


class AccountStatementResponse(BaseModel):
    """Comprehensive chronological account statement."""

    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    account_number: str
    currency: str
    balance_paise: int
    entries: list[AccountStatementItem]
