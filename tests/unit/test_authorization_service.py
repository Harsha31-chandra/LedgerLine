"""
Unit tests for LedgerLine Role-Based Access Control and Authorization Service.

Covers:
- Global role validation (ADMIN, HOLDER, AUDITOR).
- System-level actions permissions matrix.
- Account membership role hierarchy and action validation (OWNER, OPERATOR, VIEWER).
- Global AUDITOR read-only override (ensuring auditors cannot perform write actions even if their membership is OWNER or OPERATOR).
- IDOR / BOLA prevention (rejecting access to accounts where user lacks membership with AccountNotFoundError).
- Account status enforcement (preventing operations on FROZEN and CLOSED accounts).
- State immutability on rejected authorization attempts.
"""

import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

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
from backend.app.models.base import Base
from backend.app.models.user import User, UserRole
from backend.app.services.authorization_service import (
    AccountAction,
    SystemAction,
    check_account_permission,
    check_global_role,
    check_system_permission,
    get_account_for_user,
    get_account_membership,
    has_account_permission,
)


@pytest.fixture
def db_session() -> Session:
    """Provide an isolated in-memory SQLite database session for unit tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _create_user(
    db: Session,
    email: str,
    role: UserRole = UserRole.HOLDER,
    is_active: bool = True,
) -> User:
    """Helper to create and persist a test User."""
    user = User(
        email=email,
        password_hash="dummy_argon2_hash",
        full_name=f"Test {role.value}",
        role=role.value,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_account(
    db: Session,
    account_number: str,
    status: AccountStatus = AccountStatus.ACTIVE,
    balance: int = 100000,
) -> Account:
    """Helper to create and persist a test Account."""
    account = Account(
        account_number=account_number,
        account_name=f"Account {account_number}",
        currency="INR",
        balance=balance,
        status=status.value,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _create_membership(
    db: Session,
    user: User,
    account: Account,
    role: MembershipRole = MembershipRole.OWNER,
) -> AccountMembership:
    """Helper to create and persist a test AccountMembership."""
    membership = AccountMembership(
        user_id=user.id,
        account_id=account.id,
        membership_role=role.value,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


# ===========================================================================
# 1. GLOBAL ROLES AND SYSTEM PERMISSIONS TESTS
# ===========================================================================


def test_check_global_role_success(db_session: Session):
    """Verify check_global_role succeeds when user role is in allowed roles."""
    admin = _create_user(db_session, "admin@example.com", role=UserRole.ADMIN)
    holder = _create_user(db_session, "holder@example.com", role=UserRole.HOLDER)
    auditor = _create_user(db_session, "auditor@example.com", role=UserRole.AUDITOR)

    # Should not raise
    check_global_role(admin, [UserRole.ADMIN])
    check_global_role(holder, [UserRole.HOLDER, UserRole.ADMIN])
    check_global_role(auditor, [UserRole.AUDITOR])


def test_check_global_role_insufficient_role(db_session: Session):
    """Verify check_global_role raises InsufficientRoleError when user role is not permitted."""
    holder = _create_user(db_session, "holder2@example.com", role=UserRole.HOLDER)
    with pytest.raises(InsufficientRoleError) as exc_info:
        check_global_role(holder, [UserRole.ADMIN])
    assert "lacks required system permission" in str(exc_info.value)


def test_check_global_role_inactive_user(db_session: Session):
    """Verify check_global_role raises InactiveUserError for deactivated accounts."""
    inactive_admin = _create_user(
        db_session,
        "inactive_admin@example.com",
        role=UserRole.ADMIN,
        is_active=False,
    )
    with pytest.raises(InactiveUserError):
        check_global_role(inactive_admin, [UserRole.ADMIN])


@pytest.mark.parametrize(
    ("action", "allowed_role", "denied_roles"),
    [
        (SystemAction.CREATE_ACCOUNT, UserRole.ADMIN, [UserRole.HOLDER, UserRole.AUDITOR]),
        (SystemAction.MANAGE_USERS, UserRole.ADMIN, [UserRole.HOLDER, UserRole.AUDITOR]),
        (SystemAction.VIEW_ALL_USERS, UserRole.ADMIN, [UserRole.HOLDER, UserRole.AUDITOR]),
        (SystemAction.CHANGE_ACCOUNT_STATUS, UserRole.ADMIN, [UserRole.HOLDER, UserRole.AUDITOR]),
    ],
)
def test_check_system_permission_admin_exclusive(
    db_session: Session,
    action: SystemAction,
    allowed_role: UserRole,
    denied_roles: list[UserRole],
):
    """Verify admin-exclusive system actions are permitted for ADMIN and denied for other roles."""
    admin = _create_user(db_session, f"admin_{action.value}@example.com", role=allowed_role)
    check_system_permission(admin, action)

    for denied_role in denied_roles:
        user = _create_user(db_session, f"denied_{denied_role.value}_{action.value}@example.com", role=denied_role)
        with pytest.raises(InsufficientRoleError):
            check_system_permission(user, action)


def test_check_system_permission_view_audit_log(db_session: Session):
    """Verify VIEW_AUDIT_LOG is permitted for ADMIN and AUDITOR, but denied for HOLDER."""
    admin = _create_user(db_session, "audit_admin@example.com", role=UserRole.ADMIN)
    auditor = _create_user(db_session, "audit_auditor@example.com", role=UserRole.AUDITOR)
    holder = _create_user(db_session, "audit_holder@example.com", role=UserRole.HOLDER)

    check_system_permission(admin, SystemAction.VIEW_AUDIT_LOG)
    check_system_permission(auditor, SystemAction.VIEW_AUDIT_LOG)

    with pytest.raises(InsufficientRoleError):
        check_system_permission(holder, SystemAction.VIEW_AUDIT_LOG)


# ===========================================================================
# 2. ACCOUNT MEMBERSHIP ROLES & PERMISSION MATRIX TESTS
# ===========================================================================


def test_owner_membership_permissions(db_session: Session):
    """Verify OWNER membership role permits READ, OPERATE, MANAGE_MEMBERS, and UPDATE_DETAILS."""
    user = _create_user(db_session, "owner@example.com", role=UserRole.HOLDER)
    account = _create_account(db_session, "ACC-OWNER-01")
    membership = _create_membership(db_session, user, account, role=MembershipRole.OWNER)

    # All actions should succeed
    check_account_permission(user, account, membership, AccountAction.READ)
    check_account_permission(user, account, membership, AccountAction.OPERATE)
    check_account_permission(user, account, membership, AccountAction.MANAGE_MEMBERS)
    check_account_permission(user, account, membership, AccountAction.UPDATE_DETAILS)

    assert has_account_permission(user, account, membership, AccountAction.READ) is True
    assert has_account_permission(user, account, membership, AccountAction.OPERATE) is True
    assert has_account_permission(user, account, membership, AccountAction.MANAGE_MEMBERS) is True
    assert has_account_permission(user, account, membership, AccountAction.UPDATE_DETAILS) is True


def test_operator_membership_permissions(db_session: Session):
    """Verify OPERATOR permits READ and OPERATE, but rejects MANAGE_MEMBERS and UPDATE_DETAILS."""
    user = _create_user(db_session, "operator@example.com", role=UserRole.HOLDER)
    account = _create_account(db_session, "ACC-OPERATOR-01")
    membership = _create_membership(db_session, user, account, role=MembershipRole.OPERATOR)

    # Allowed
    check_account_permission(user, account, membership, AccountAction.READ)
    check_account_permission(user, account, membership, AccountAction.OPERATE)

    # Denied
    with pytest.raises(InsufficientMembershipRoleError):
        check_account_permission(user, account, membership, AccountAction.MANAGE_MEMBERS)

    with pytest.raises(InsufficientMembershipRoleError):
        check_account_permission(user, account, membership, AccountAction.UPDATE_DETAILS)

    assert has_account_permission(user, account, membership, AccountAction.READ) is True
    assert has_account_permission(user, account, membership, AccountAction.OPERATE) is True
    assert has_account_permission(user, account, membership, AccountAction.MANAGE_MEMBERS) is False
    assert has_account_permission(user, account, membership, AccountAction.UPDATE_DETAILS) is False


def test_viewer_membership_permissions(db_session: Session):
    """Verify VIEWER permits READ, but rejects OPERATE, MANAGE_MEMBERS, and UPDATE_DETAILS."""
    user = _create_user(db_session, "viewer@example.com", role=UserRole.HOLDER)
    account = _create_account(db_session, "ACC-VIEWER-01")
    membership = _create_membership(db_session, user, account, role=MembershipRole.VIEWER)

    # Allowed
    check_account_permission(user, account, membership, AccountAction.READ)

    # Denied
    with pytest.raises(InsufficientMembershipRoleError):
        check_account_permission(user, account, membership, AccountAction.OPERATE)

    with pytest.raises(InsufficientMembershipRoleError):
        check_account_permission(user, account, membership, AccountAction.MANAGE_MEMBERS)

    with pytest.raises(InsufficientMembershipRoleError):
        check_account_permission(user, account, membership, AccountAction.UPDATE_DETAILS)

    assert has_account_permission(user, account, membership, AccountAction.READ) is True
    assert has_account_permission(user, account, membership, AccountAction.OPERATE) is False
    assert has_account_permission(user, account, membership, AccountAction.MANAGE_MEMBERS) is False
    assert has_account_permission(user, account, membership, AccountAction.UPDATE_DETAILS) is False


# ===========================================================================
# 3. GLOBAL AUDITOR READ-ONLY CONFLICT OVERRIDE TESTS
# ===========================================================================


@pytest.mark.parametrize(
    "membership_role",
    [MembershipRole.OWNER, MembershipRole.OPERATOR, MembershipRole.VIEWER],
)
def test_global_auditor_read_only_override_across_all_memberships(
    db_session: Session,
    membership_role: MembershipRole,
):
    """Verify that a global AUDITOR remains read-only even when their membership role is OWNER or OPERATOR."""
    auditor = _create_user(db_session, f"auditor_{membership_role.value}@example.com", role=UserRole.AUDITOR)
    account = _create_account(db_session, f"ACC-AUDIT-{membership_role.value}")
    membership = _create_membership(db_session, auditor, account, role=membership_role)

    # Read action must always succeed for member auditor
    check_account_permission(auditor, account, membership, AccountAction.READ)
    assert has_account_permission(auditor, account, membership, AccountAction.READ) is True

    # Mutating actions must always raise AuditorReadOnlyViolationError
    with pytest.raises(AuditorReadOnlyViolationError) as exc_op:
        check_account_permission(auditor, account, membership, AccountAction.OPERATE)
    assert "Auditors are restricted to read-only access" in str(exc_op.value)
    assert has_account_permission(auditor, account, membership, AccountAction.OPERATE) is False

    with pytest.raises(AuditorReadOnlyViolationError):
        check_account_permission(auditor, account, membership, AccountAction.MANAGE_MEMBERS)
    assert has_account_permission(auditor, account, membership, AccountAction.MANAGE_MEMBERS) is False

    with pytest.raises(AuditorReadOnlyViolationError):
        check_account_permission(auditor, account, membership, AccountAction.UPDATE_DETAILS)
    assert has_account_permission(auditor, account, membership, AccountAction.UPDATE_DETAILS) is False


# ===========================================================================
# 4. IDOR / BOLA PROTECTION TESTS
# ===========================================================================


def test_idor_holder_cannot_access_other_holder_account(db_session: Session):
    """Verify that a HOLDER cannot access an account belonging to another user (anti-IDOR/BOLA)."""
    user_a = _create_user(db_session, "user_a@example.com", role=UserRole.HOLDER)
    user_b = _create_user(db_session, "user_b@example.com", role=UserRole.HOLDER)

    account_a = _create_account(db_session, "ACC-A-100")
    account_b = _create_account(db_session, "ACC-B-200")

    _create_membership(db_session, user_a, account_a, role=MembershipRole.OWNER)
    _create_membership(db_session, user_b, account_b, role=MembershipRole.OWNER)

    # User A accesses Account A -> success
    acc, mem = get_account_for_user(db_session, user_a, account_a.id, AccountAction.READ)
    assert acc.id == account_a.id
    assert mem.user_id == user_a.id

    # User A attempts to access Account B -> raises AccountNotFoundError (anti-enumeration)
    with pytest.raises(AccountNotFoundError) as exc_info:
        get_account_for_user(db_session, user_a, account_b.id, AccountAction.READ)
    assert "not found or access denied" in str(exc_info.value) or "not found" in str(exc_info.value)

    # User B attempts to access Account A -> raises AccountNotFoundError
    with pytest.raises(AccountNotFoundError):
        get_account_for_user(db_session, user_b, account_a.id, AccountAction.READ)


def test_idor_user_cannot_access_unowned_account_by_guessing_uuid(db_session: Session):
    """Verify that querying a random / guessed account UUID returns AccountNotFoundError."""
    user = _create_user(db_session, "random_guesser@example.com", role=UserRole.HOLDER)
    non_existent_uuid = uuid.uuid4()

    with pytest.raises(AccountNotFoundError):
        get_account_for_user(db_session, user, non_existent_uuid, AccountAction.READ)


def test_idor_auditor_without_membership_cannot_access_account(db_session: Session):
    """Verify that an AUDITOR cannot access accounts for which they have no active membership."""
    auditor = _create_user(db_session, "unassigned_auditor@example.com", role=UserRole.AUDITOR)
    account = _create_account(db_session, "ACC-PRIVATE-999")

    # Auditor is not a member of account
    with pytest.raises(AccountNotFoundError):
        get_account_for_user(db_session, auditor, account.id, AccountAction.READ)


def test_idor_admin_without_membership_cannot_operate_account(db_session: Session):
    """Verify that an ADMIN without account membership cannot access or operate an account."""
    admin = _create_user(db_session, "unassigned_admin@example.com", role=UserRole.ADMIN)
    account = _create_account(db_session, "ACC-CUSTOMER-777")

    with pytest.raises(AccountNotFoundError):
        get_account_for_user(db_session, admin, account.id, AccountAction.OPERATE)


# ===========================================================================
# 5. ACCOUNT STATUS CONSTRAINT TESTS
# ===========================================================================


@pytest.mark.parametrize("status", [AccountStatus.FROZEN, AccountStatus.CLOSED])
def test_frozen_and_closed_accounts_reject_operational_actions(
    db_session: Session,
    status: AccountStatus,
):
    """Verify that FROZEN and CLOSED accounts reject OPERATE actions with AccountStatusError."""
    user = _create_user(db_session, f"user_{status.value}@example.com", role=UserRole.HOLDER)
    account = _create_account(db_session, f"ACC-STATUS-{status.value}", status=status)
    membership = _create_membership(db_session, user, account, role=MembershipRole.OWNER)

    # Read action is still permitted on frozen/closed accounts for transparency
    check_account_permission(user, account, membership, AccountAction.READ)
    assert has_account_permission(user, account, membership, AccountAction.READ) is True

    # Mutating operation must raise AccountStatusError
    with pytest.raises(AccountStatusError) as exc_info:
        check_account_permission(user, account, membership, AccountAction.OPERATE)
    assert f"is {status.value.lower()}" in str(exc_info.value)
    assert has_account_permission(user, account, membership, AccountAction.OPERATE) is False


# ===========================================================================
# 6. INACTIVE USER CONSTRAINT TESTS
# ===========================================================================


def test_inactive_user_rejected_on_all_account_actions(db_session: Session):
    """Verify that a deactivated user is blocked from all account actions with InactiveUserError."""
    inactive_user = _create_user(
        db_session,
        "inactive_holder@example.com",
        role=UserRole.HOLDER,
        is_active=False,
    )
    account = _create_account(db_session, "ACC-INACTIVE-01")
    membership = _create_membership(db_session, inactive_user, account, role=MembershipRole.OWNER)

    for action in AccountAction:
        with pytest.raises(InactiveUserError):
            check_account_permission(inactive_user, account, membership, action)
        assert has_account_permission(inactive_user, account, membership, action) is False


# ===========================================================================
# 7. DATABASE STATE IMMUTABILITY ON REJECTED AUTHORIZATION
# ===========================================================================


def test_rejected_authorization_does_not_mutate_database_state(db_session: Session):
    """Verify that unauthorized requests do not alter account balances, status, or memberships."""
    owner = _create_user(db_session, "safe_owner@example.com", role=UserRole.HOLDER)
    attacker = _create_user(db_session, "safe_attacker@example.com", role=UserRole.HOLDER)

    initial_balance = 500000  # 5000.00 INR
    account = _create_account(db_session, "ACC-SAFE-001", balance=initial_balance)
    _create_membership(db_session, owner, account, role=MembershipRole.OWNER)

    initial_updated_at = account.updated_at

    # Attacker tries to operate on owner's account
    with pytest.raises(AccountNotFoundError):
        get_account_for_user(db_session, attacker, account.id, AccountAction.OPERATE)

    # Refresh account and verify state remains completely untouched
    db_session.refresh(account)
    assert account.balance == initial_balance
    assert account.status == AccountStatus.ACTIVE
    assert account.updated_at == initial_updated_at

    # Verify no rogue memberships were inserted
    memberships = db_session.query(AccountMembership).filter_by(account_id=account.id).all()
    assert len(memberships) == 1
    assert memberships[0].user_id == owner.id
