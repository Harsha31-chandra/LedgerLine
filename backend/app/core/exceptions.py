"""
Custom domain exceptions for LedgerLine.

Provides domain error classes for authentication, credential validation,
user lifecycle, session management, authorization, financial ledgers,
and idempotency.
"""


class LedgerLineError(Exception):
    """Base exception for all LedgerLine application and domain errors."""


class AuthenticationError(LedgerLineError):
    """Raised when user credential validation fails (invalid email or password)."""


class UserAlreadyExistsError(LedgerLineError):
    """Raised when registering a user with an email that is already registered."""


class InactiveUserError(LedgerLineError):
    """Raised when an inactive/deactivated user attempts authentication or operations."""


class SessionError(LedgerLineError):
    """Base exception for session-related validation and lifecycle errors."""


class SessionNotFoundError(SessionError):
    """Raised when a session token does not match any existing session."""


class SessionExpiredError(SessionError):
    """Raised when a session has passed its expiration timestamp."""


class SessionRevokedError(SessionError):
    """Raised when an operation is attempted with an explicitly revoked session."""


class AuthorizationError(LedgerLineError):
    """Base exception for all authorization and access control errors."""


class InsufficientRoleError(AuthorizationError):
    """Raised when a user lacks the required system-level global role."""


class AccountAccessDeniedError(AuthorizationError):
    """Raised when an authenticated user is denied access to a specific account."""


class AccountNotFoundError(AuthorizationError):
    """Raised when an account is not found or when a user is not authorized to know it exists."""


class AuditorReadOnlyViolationError(AuthorizationError):
    """Raised when an auditor attempts any write, mutation, or operational action."""


class InsufficientMembershipRoleError(AuthorizationError):
    """Raised when an account member lacks the required membership role for an action."""


class AccountStatusError(AuthorizationError):
    """Raised when an account is not in a valid status to process operations (e.g. FROZEN or CLOSED)."""


class FinancialError(LedgerLineError):
    """Base exception for all financial calculation and ledger errors."""


class InsufficientFundsError(FinancialError):
    """Raised when an account has insufficient funds for a withdrawal or transfer."""


class SameAccountTransferError(FinancialError):
    """Raised when a transfer specifies identical source and destination accounts."""


class ClearingAccountTransferError(FinancialError):
    """Raised when attempting a transfer to or from the system clearing account."""


class InvalidAmountError(FinancialError):
    """Raised when a monetary amount is zero, negative, or invalid."""


class CurrencyMismatchError(FinancialError):
    """Raised when transaction accounts have mismatched currencies."""


class UnbalancedLedgerError(FinancialError):
    """Raised when a double-entry posting does not have balanced debits and credits."""


class IdempotencyError(LedgerLineError):
    """Base exception for idempotency key validation and replay errors."""


class IdempotencyCollisionError(IdempotencyError):
    """Raised when an idempotency key is reused with a different request payload."""


class IdempotencyInFlightError(IdempotencyError):
    """Raised when a concurrent request with the same idempotency key is already executing."""
