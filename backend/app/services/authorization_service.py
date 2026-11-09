"""
Role-Based Access Control (RBAC) and Account-Level Authorization Service.

Provides:
- Global role enforcement (ADMIN, HOLDER, AUDITOR).
- Account membership role enforcement (OWNER, OPERATOR, VIEWER).
- Fine-grained permission resolution preventing Broken Object Level Authorization (BOLA/IDOR).
- Conflict resolution ensuring global AUDITOR users remain strictly read-only regardless
  of account membership role.
- Anti-enumeration defense: returning AccountNotFoundError for missing accounts or
  unauthorized account queries.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Final
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from backend.app.core.exceptions import (
    AccountNotFoundError,
    AccountStatusError,
    AuditorReadOnlyViolationError,
    InactiveUserError,
    InsufficientMembershipRoleError,
    InsufficientRoleError,
)
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.user import User, UserRole

__all__ = [
    "ACCOUNT_ACTION_MIN_MEMBERSHIP",
    "MEMBERSHIP_ROLE_HIERARCHY",
    "SYSTEM_ROLE_PERMISSIONS",
    "WRITE_ACCOUNT_ACTIONS",
    "AccountAction",
    "SystemAction",
    "check_account_permission",
    "check_global_role",
    "check_system_permission",
    "get_account_for_user",
    "get_account_membership",
    "has_account_permission",
]


class AccountAction(StrEnum):
    """Actions performed within the context of a specific account."""

    READ = "READ"  # View account details, balances, ledger entries, transactions
    OPERATE = "OPERATE"  # Execute operational mutations (deposits, withdrawals, transfers)
    MANAGE_MEMBERS = "MANAGE_MEMBERS"  # Add, update, or remove account memberships
    UPDATE_DETAILS = "UPDATE_DETAILS"  # Update account name / metadata


class SystemAction(StrEnum):
    """Actions performed at the system/global level (not bound to an individual account)."""

    CREATE_ACCOUNT = "CREATE_ACCOUNT"
    MANAGE_USERS = "MANAGE_USERS"
    VIEW_ALL_USERS = "VIEW_ALL_USERS"
    VIEW_AUDIT_LOG = "VIEW_AUDIT_LOG"
    CHANGE_ACCOUNT_STATUS = "CHANGE_ACCOUNT_STATUS"
    VIEW_ALL_ACCOUNTS = "VIEW_ALL_ACCOUNTS"


# System-level role permissions mapping
SYSTEM_ROLE_PERMISSIONS: Final[dict[SystemAction, frozenset[UserRole]]] = {
    SystemAction.CREATE_ACCOUNT: frozenset({UserRole.ADMIN}),
    SystemAction.MANAGE_USERS: frozenset({UserRole.ADMIN}),
    SystemAction.VIEW_ALL_USERS: frozenset({UserRole.ADMIN}),
    SystemAction.VIEW_AUDIT_LOG: frozenset({UserRole.ADMIN, UserRole.AUDITOR}),
    SystemAction.CHANGE_ACCOUNT_STATUS: frozenset({UserRole.ADMIN}),
    SystemAction.VIEW_ALL_ACCOUNTS: frozenset({UserRole.ADMIN}),
}

# Account membership role hierarchy level (higher number = greater privilege)
MEMBERSHIP_ROLE_HIERARCHY: Final[dict[MembershipRole, int]] = {
    MembershipRole.VIEWER: 1,
    MembershipRole.OPERATOR: 2,
    MembershipRole.OWNER: 3,
}

# Required minimum membership role for account actions
ACCOUNT_ACTION_MIN_MEMBERSHIP: Final[dict[AccountAction, MembershipRole]] = {
    AccountAction.READ: MembershipRole.VIEWER,
    AccountAction.OPERATE: MembershipRole.OPERATOR,
    AccountAction.MANAGE_MEMBERS: MembershipRole.OWNER,
    AccountAction.UPDATE_DETAILS: MembershipRole.OWNER,
}

# Set of mutating / write account actions that are strictly forbidden to AUDITORs
WRITE_ACCOUNT_ACTIONS: Final[frozenset[AccountAction]] = frozenset({
    AccountAction.OPERATE,
    AccountAction.MANAGE_MEMBERS,
    AccountAction.UPDATE_DETAILS,
})


def check_global_role(user: User, allowed_roles: Iterable[UserRole | str]) -> None:
    """Ensure user is active and has one of the specified system roles.

    Args:
        user: Authenticated User entity.
        allowed_roles: Collection of permitted UserRole values or strings.

    Raises:
        InactiveUserError: If user account is deactivated.
        InsufficientRoleError: If user role is not in allowed_roles.
    """
    if not user.is_active:
        raise InactiveUserError("User account is inactive")

    normalized_allowed = {
        role.value if isinstance(role, UserRole) else str(role).upper()
        for role in allowed_roles
    }
    user_role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role).upper()

    if user_role_str not in normalized_allowed:
        raise InsufficientRoleError(
            f"User role '{user.role}' lacks required system permission. Allowed roles: {sorted(normalized_allowed)}"
        )


def check_system_permission(user: User, action: SystemAction) -> None:
    """Verify that a user has permission to execute a system-level action.

    Args:
        user: Authenticated User entity.
        action: SystemAction being attempted.

    Raises:
        InactiveUserError: If user account is deactivated.
        InsufficientRoleError: If user role is not permitted for the action.
    """
    if not user.is_active:
        raise InactiveUserError("User account is inactive")

    allowed_roles = SYSTEM_ROLE_PERMISSIONS.get(action, frozenset())
    check_global_role(user, allowed_roles)


def get_account_membership(
    db: DbSession,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> AccountMembership | None:
    """Query the active account membership for a user on an account.

    Args:
        db: Active database session.
        user_id: UUID of user.
        account_id: UUID of account.

    Returns:
        AccountMembership instance if found, or None.
    """
    stmt = select(AccountMembership).where(
        AccountMembership.user_id == user_id,
        AccountMembership.account_id == account_id,
    )
    return db.scalars(stmt).first()


def check_account_permission(
    user: User,
    account: Account,
    membership: AccountMembership | None,
    action: AccountAction,
) -> None:
    """Enforce account-level authorization policy against user and membership.

    Policies:
    1. Inactive users are rejected immediately with InactiveUserError.
    2. Missing membership raises AccountNotFoundError (anti-enumeration / IDOR defense).
    3. Global AUDITOR role is strictly read-only: any write action (OPERATE, MANAGE_MEMBERS,
       UPDATE_DETAILS) raises AuditorReadOnlyViolationError even if membership role is OWNER/OPERATOR.
    4. Membership role must meet or exceed the required minimum role for the action.
    5. Operational actions (OPERATE) require the account to be in ACTIVE status.

    Args:
        user: Authenticated User entity.
        account: Account entity being accessed.
        membership: AccountMembership entity mapping user to account, or None.
        action: AccountAction being attempted.

    Raises:
        InactiveUserError: If user is inactive.
        AccountNotFoundError: If user has no membership on the account (prevents IDOR existence disclosure).
        AuditorReadOnlyViolationError: If global AUDITOR attempts any write action.
        InsufficientMembershipRoleError: If membership role does not satisfy action requirements.
        AccountStatusError: If operational action is attempted on a non-ACTIVE account.
    """
    # 1. Inactive user check
    if not user.is_active:
        raise InactiveUserError("User account is inactive")

    # 2. Membership existence check (anti-IDOR: reject if user is not a member)
    if membership is None or membership.user_id != user.id or membership.account_id != account.id:
        raise AccountNotFoundError(f"Account {account.id} not found or access denied")

    # 3. Global AUDITOR read-only constraint override
    user_role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role).upper()
    if user_role_str == UserRole.AUDITOR and action in WRITE_ACCOUNT_ACTIONS:
        raise AuditorReadOnlyViolationError(
            f"Auditors are restricted to read-only access and cannot perform write action '{action.value}'"
        )

    # 4. Membership role sufficiency check
    min_role = ACCOUNT_ACTION_MIN_MEMBERSHIP[action]
    membership_role_enum = (
        membership.membership_role
        if isinstance(membership.membership_role, MembershipRole)
        else MembershipRole(membership.membership_role)
    )

    user_level = MEMBERSHIP_ROLE_HIERARCHY.get(membership_role_enum, 0)
    req_level = MEMBERSHIP_ROLE_HIERARCHY[min_role]

    if user_level < req_level:
        raise InsufficientMembershipRoleError(
            f"Account membership role '{membership.membership_role}' cannot perform '{action.value}' "
            f"(requires minimum role '{min_role.value}')"
        )

    # 5. Account status constraint for operational actions
    if action == AccountAction.OPERATE and account.status != AccountStatus.ACTIVE:
        raise AccountStatusError(
            f"Account '{account.id}' is {account.status.lower()} and cannot process operations"
        )


def has_account_permission(
    user: User,
    account: Account,
    membership: AccountMembership | None,
    action: AccountAction,
) -> bool:
    """Return True if user is authorized for the action on the account, False otherwise."""
    try:
        check_account_permission(
            user=user,
            account=account,
            membership=membership,
            action=action,
        )
        return True
    except (
        AccountNotFoundError,
        AccountStatusError,
        AuditorReadOnlyViolationError,
        InactiveUserError,
        InsufficientMembershipRoleError,
    ):
        return False


def get_account_for_user(
    db: DbSession,
    user: User,
    account_id: uuid.UUID,
    action: AccountAction = AccountAction.READ,
) -> tuple[Account, AccountMembership]:
    """Retrieve an account and enforce user authorization for the requested action.

    Args:
        db: Active database session.
        user: Authenticated User entity.
        account_id: UUID of account to access.
        action: AccountAction being requested (defaults to AccountAction.READ).

    Returns:
        Tuple of (Account, AccountMembership).

    Raises:
        AccountNotFoundError: If account does not exist or user has no membership.
        AuditorReadOnlyViolationError: If global AUDITOR attempts a write action.
        InsufficientMembershipRoleError: If user's membership role is insufficient.
        AccountStatusError: If operational action is attempted on non-ACTIVE account.
        InactiveUserError: If user account is deactivated.
    """
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"Account {account_id} not found")

    membership = get_account_membership(db, user_id=user.id, account_id=account_id)
    check_account_permission(
        user=user,
        account=account,
        membership=membership,
        action=action,
    )
    # At this point membership is guaranteed to be non-None by check_account_permission
    assert membership is not None
    return account, membership
