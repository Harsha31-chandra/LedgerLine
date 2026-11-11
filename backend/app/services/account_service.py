"""
Financial account service for LedgerLine.

Provides:
- Account lifecycle management (creation, queries, status updates).
- Atomically paired account and initial OWNER membership creation.
- Strict authorization enforcement preventing IDOR/BOLA or privilege escalation.
- System clearing account provisioning for balanced double-entry deposits and withdrawals.
"""

import secrets
from typing import Sequence
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from backend.app.core.exceptions import (
    AccountNotFoundError,
    AccountStatusError,
    AuditorReadOnlyViolationError,
    InactiveUserError,
    InsufficientRoleError,
)
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.user import User, UserRole
from backend.app.services.audit_service import record_audit_event
from backend.app.services.authorization_service import (
    AccountAction,
    SystemAction,
    check_account_permission,
    check_system_permission,
    get_account_membership,
)

SYSTEM_CLEARING_ACCOUNT_NUMBER = "SYSTEM_CLEARING"
SYSTEM_VAULT_INITIAL_BALANCE = 0  # Starts at 0; strictly reflects double-entry ledger entries

__all__ = [
    "SYSTEM_CLEARING_ACCOUNT_NUMBER",
    "assign_account_membership",
    "change_account_status",
    "create_account",
    "create_onboarding_account",
    "get_account_by_id",
    "get_or_create_system_clearing_account",
    "list_all_accounts",
    "list_user_accounts",
    "update_account_details",
]


def _generate_account_number() -> str:
    """Generate a clean, unique 12-digit human-readable account number."""
    random_digits = "".join(secrets.choice("0123456789") for _ in range(10))
    return f"LL-{random_digits}"


def get_or_create_system_clearing_account(db: DbSession) -> Account:
    """Retrieve or initialize the centralized system clearing account for double-entry cash movements.

    Concurrency-safe: uses a nested transaction (savepoint) to catch race conditions and resolve
    concurrent initialization cleanly without unhandled IntegrityError exceptions.
    """
    stmt = select(Account).where(Account.account_number == SYSTEM_CLEARING_ACCOUNT_NUMBER)
    clearing_acc = db.scalars(stmt).first()
    if clearing_acc is not None:
        return clearing_acc

    try:
        with db.begin_nested():
            clearing_acc = Account(
                account_number=SYSTEM_CLEARING_ACCOUNT_NUMBER,
                account_name="System Central Clearing Reserve",
                currency="INR",
                balance=SYSTEM_VAULT_INITIAL_BALANCE,
                status=AccountStatus.ACTIVE.value,
            )
            db.add(clearing_acc)
            db.flush()
        return clearing_acc
    except IntegrityError:
        # Concurrent worker inserted the clearing account first
        stmt = select(Account).where(Account.account_number == SYSTEM_CLEARING_ACCOUNT_NUMBER)
        clearing_acc = db.scalars(stmt).first()
        if clearing_acc is not None:
            return clearing_acc
        raise


def create_account(
    db: DbSession,
    creator_user: User,
    account_name: str,
    currency: str = "INR",
    owner_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> tuple[Account, AccountMembership]:
    """Create a new financial account and assign its initial OWNER membership atomically.

    Enforces:
    - Creator must have UserRole.ADMIN (SystemAction.CREATE_ACCOUNT).
    - Designates either owner_user_id (if valid and active) or creator as the initial OWNER.
    - Records audit event atomically.

    Args:
        db: Active SQLAlchemy database session.
        creator_user: Authenticated user initiating account creation.
        account_name: Name/label for the account.
        currency: 3-character ISO currency code (default 'INR').
        owner_user_id: Optional user to assign as initial OWNER.
        ip_address: Client IP address.

    Returns:
        Tuple of (Account, AccountMembership).

    Raises:
        InactiveUserError: If creator or target owner is inactive.
        InsufficientRoleError: If creator lacks ADMIN global role.
        ValueError: If designated owner user does not exist.
    """
    check_system_permission(creator_user, SystemAction.CREATE_ACCOUNT)

    # Determine initial owner
    target_owner_id = owner_user_id if owner_user_id is not None else creator_user.id
    target_owner = db.get(User, target_owner_id)
    if target_owner is None:
        raise ValueError(f"Designated owner user {target_owner_id} does not exist")
    if not target_owner.is_active:
        raise InactiveUserError(f"Designated owner user {target_owner_id} is inactive")

    # Generate unique account number
    account_number = _generate_account_number()
    while db.scalars(select(Account).where(Account.account_number == account_number)).first() is not None:
        account_number = _generate_account_number()

    # 1. Create Account entity
    account = Account(
        account_number=account_number,
        account_name=account_name.strip(),
        currency=currency.upper(),
        balance=0,
        status=AccountStatus.ACTIVE.value,
    )
    db.add(account)
    db.flush()

    # 2. Atomically create initial OWNER membership
    membership = AccountMembership(
        user_id=target_owner.id,
        account_id=account.id,
        membership_role=MembershipRole.OWNER.value,
    )
    db.add(membership)
    db.flush()

    # 3. Record Audit Event
    record_audit_event(
        db=db,
        action="ACCOUNT_CREATED",
        entity_type="Account",
        entity_id=account.id,
        actor_user_id=creator_user.id,
        metadata={
            "account_number": account.account_number,
            "account_name": account.account_name,
            "owner_user_id": str(target_owner.id),
        },
        ip_address=ip_address,
    )

    db.commit()
    db.refresh(account)
    db.refresh(membership)
    return account, membership


def create_onboarding_account(
    db: DbSession,
    user: User,
    account_name: str,
    currency: str = "INR",
    initial_deposit_paise: int = 0,
    ip_address: str | None = None,
) -> tuple[Account, AccountMembership]:
    """Create a new financial account for the authenticated user during self-service onboarding.

    Enforces:
    - User must be active.
    - Auditor role is prohibited from creating accounts (read-only).
    - Designates authenticated user as initial OWNER.
    - Optional demo initial deposit:
      - Validates settings.enable_demo_funds is True.
      - Enforces that user has not previously claimed demo funds.
      - Executes double-entry deposit through execute_deposit (debits SYSTEM_CLEARING, credits account).
      - Records DEMO_INITIAL_DEPOSIT_CLAIMED in audit_events.
    - Records ACCOUNT_CREATED audit event.
    - Commits transaction atomically.
    """
    from backend.app.config import settings
    from backend.app.models.audit_event import AuditEvent
    from backend.app.services.transaction_service import execute_deposit

    if not user.is_active:
        raise InactiveUserError(f"User {user.id} is inactive")

    if user.role == UserRole.AUDITOR:
        raise AuditorReadOnlyViolationError("Auditor role is restricted to read-only access")

    cleaned_name = account_name.strip()
    if not cleaned_name:
        raise ValueError("Account name cannot be empty")

    cleaned_currency = currency.strip().upper()
    if len(cleaned_currency) != 3:
        raise ValueError("Currency must be a 3-character ISO code")

    # Generate unique account number
    account_number = _generate_account_number()
    while db.scalars(select(Account).where(Account.account_number == account_number)).first() is not None:
        account_number = _generate_account_number()

    # 1. Create Account entity
    account = Account(
        account_number=account_number,
        account_name=cleaned_name,
        currency=cleaned_currency,
        balance=0,
        status=AccountStatus.ACTIVE.value,
    )
    db.add(account)
    db.flush()

    # 2. Atomically create initial OWNER membership
    membership = AccountMembership(
        user_id=user.id,
        account_id=account.id,
        membership_role=MembershipRole.OWNER.value,
    )
    db.add(membership)
    db.flush()

    # 3. Record Account Created Audit Event
    record_audit_event(
        db=db,
        action="ACCOUNT_CREATED",
        entity_type="Account",
        entity_id=account.id,
        actor_user_id=user.id,
        metadata={
            "account_number": account.account_number,
            "account_name": account.account_name,
            "owner_user_id": str(user.id),
            "source": "onboarding",
        },
        ip_address=ip_address,
    )

    # 4. Handle optional Demo Opening Deposit
    if initial_deposit_paise > 0:
        if not settings.enable_demo_funds:
            raise ValueError("Demo opening funds are not enabled in this environment")

        if initial_deposit_paise > 1_000_000:
            raise ValueError("Demo opening deposit cannot exceed ₹10,000 (1,000,000 paise)")

        # Verify user has not already claimed demo funds
        stmt = select(AuditEvent).where(
            AuditEvent.actor_user_id == user.id,
            AuditEvent.action == "DEMO_INITIAL_DEPOSIT_CLAIMED",
        )
        if db.scalars(stmt).first() is not None:
            raise ValueError("Demo funds have already been claimed for this user account")

        # Execute double-entry deposit through execute_deposit
        execute_deposit(
            db=db,
            user=user,
            account_id=account.id,
            amount_paise=initial_deposit_paise,
            idempotency_key=f"onboard-{account.id}",
            description="Demo Funds — Initial Sample Opening Balance",
            ip_address=ip_address,
        )

        record_audit_event(
            db=db,
            action="DEMO_INITIAL_DEPOSIT_CLAIMED",
            entity_type="Account",
            entity_id=account.id,
            actor_user_id=user.id,
            metadata={
                "account_id": str(account.id),
                "account_number": account.account_number,
                "amount_paise": initial_deposit_paise,
            },
            ip_address=ip_address,
        )

    db.commit()
    db.refresh(account)
    db.refresh(membership)
    return account, membership


def get_account_by_id(
    db: DbSession,
    user: User,
    account_id: uuid.UUID,
) -> tuple[Account, AccountMembership]:
    """Retrieve an account and verify user's read access (anti-IDOR: returns 404 if not a member)."""
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"Account {account_id} not found")

    membership = get_account_membership(db, user_id=user.id, account_id=account_id)
    check_account_permission(user, account, membership, AccountAction.READ)
    assert membership is not None
    return account, membership


def list_user_accounts(
    db: DbSession,
    user: User,
) -> list[tuple[Account, str]]:
    """List all accounts for which the authenticated user has an active membership.

    Args:
        db: Active SQLAlchemy database session.
        user: Authenticated user entity.

    Returns:
        List of tuples: (Account, membership_role string).
    """
    if not user.is_active:
        raise InactiveUserError("User account is inactive")

    stmt = (
        select(Account, AccountMembership.membership_role)
        .join(AccountMembership, Account.id == AccountMembership.account_id)
        .where(AccountMembership.user_id == user.id)
        .order_by(Account.created_at.desc())
    )
    results = db.execute(stmt).all()
    return [(row[0], row[1]) for row in results]


def list_all_accounts(
    db: DbSession,
    admin_user: User | None = None,
    include_system_clearing: bool = False,
) -> list[Account]:
    """List all accounts in the system for administrative oversight.

    Enforces:
    - If admin_user is provided, verifies user is active and has SystemAction.VIEW_ALL_ACCOUNTS (ADMIN role).
    - Excludes SYSTEM_CLEARING by default to prevent exposure as an ordinary customer account.
    - Orders accounts by created_at descending.
    - Does not grant account membership or operational permissions.

    Args:
        db: Active SQLAlchemy database session.
        admin_user: Optional authenticated user (verified for administrative permission).
        include_system_clearing: Whether to include the internal system clearing vault account.

    Returns:
        List of Account model instances.
    """
    if admin_user is not None:
        if not admin_user.is_active:
            raise InactiveUserError("User account is inactive")
        check_system_permission(admin_user, SystemAction.VIEW_ALL_ACCOUNTS)

    stmt = select(Account).order_by(Account.created_at.desc())
    if not include_system_clearing:
        stmt = stmt.where(Account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER)

    return list(db.scalars(stmt).all())


def update_account_details(
    db: DbSession,
    user: User,
    account_id: uuid.UUID,
    new_account_name: str,
    ip_address: str | None = None,
) -> Account:
    """Update permitted account metadata (requires OWNER membership)."""
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"Account {account_id} not found")

    membership = get_account_membership(db, user_id=user.id, account_id=account_id)
    check_account_permission(user, account, membership, AccountAction.UPDATE_DETAILS)

    old_name = account.account_name
    account.account_name = new_account_name.strip()
    db.add(account)

    record_audit_event(
        db=db,
        action="ACCOUNT_UPDATED",
        entity_type="Account",
        entity_id=account.id,
        actor_user_id=user.id,
        metadata={"old_name": old_name, "new_name": account.account_name},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(account)
    return account



def change_account_status(
    db: DbSession,
    admin_user: User,
    account_id: uuid.UUID,
    new_status: AccountStatus,
    ip_address: str | None = None,
) -> Account:
    """Change an account's lifecycle status (Admin-only)."""
    check_system_permission(admin_user, SystemAction.CHANGE_ACCOUNT_STATUS)

    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"Account {account_id} not found")

    if account.account_number == SYSTEM_CLEARING_ACCOUNT_NUMBER:
        raise AccountStatusError("System clearing account status cannot be modified")

    old_status = account.status
    account.status = new_status.value
    db.add(account)

    record_audit_event(
        db=db,
        action="ACCOUNT_STATUS_CHANGED",
        entity_type="Account",
        entity_id=str(account.id),
        actor_user_id=admin_user.id,
        metadata={
            "account_id": str(account.id),
            "account_number": account.account_number,
            "old_status": old_status,
            "new_status": new_status.value,
        },
        ip_address=ip_address,
    )

    db.commit()
    db.refresh(account)
    return account


def assign_account_membership(
    db: DbSession,
    admin_user: User,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    role: MembershipRole,
    ip_address: str | None = None,
) -> AccountMembership:
    """Assign or update a user's membership role on an account. Admin only."""
    check_system_permission(admin_user, SystemAction.MANAGE_USERS)

    account = db.get(Account, account_id)
    if account is None or account.account_number == SYSTEM_CLEARING_ACCOUNT_NUMBER:
        raise AccountNotFoundError(f"Account {account_id} not found")

    target_user = db.get(User, user_id)
    if target_user is None:
        raise ValueError(f"User {user_id} not found")
    if not target_user.is_active:
        raise InactiveUserError(f"User {user_id} is inactive")

    stmt = select(AccountMembership).where(
        AccountMembership.user_id == user_id,
        AccountMembership.account_id == account_id,
    )
    membership = db.scalars(stmt).first()
    if membership is not None:
        membership.membership_role = role.value
    else:
        membership = AccountMembership(
            user_id=user_id,
            account_id=account_id,
            membership_role=role.value,
        )
        db.add(membership)

    record_audit_event(
        db=db,
        action="MEMBERSHIP_ASSIGNED",
        entity_type="AccountMembership",
        entity_id=account.id,
        actor_user_id=admin_user.id,
        metadata={
            "account_id": str(account.id),
            "account_number": account.account_number,
            "target_user_id": str(user_id),
            "membership_role": role.value,
        },
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(membership)
    return membership

