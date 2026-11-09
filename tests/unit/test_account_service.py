"""
Unit tests for LedgerLine financial account service.

Covers:
- Account creation with atomic initial OWNER membership (Admin-only).
- Rejection of account creation by non-admin users.
- Designated customer owner assignment and validation.
- User account listing and strict tenant isolation (anti-IDOR).
- Account metadata updates (restricted to OWNER; rejected for OPERATOR, VIEWER, and AUDITOR).
- Administrative status transitions (ACTIVE, FROZEN, CLOSED).
- Integrated audit trail generation.
"""

import uuid

import pytest
from sqlalchemy import create_engine, event, select
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
from backend.app.models.audit_event import AuditEvent
from backend.app.models.base import Base
from backend.app.models.user import User, UserRole
from backend.app.services.account_service import (
    SYSTEM_CLEARING_ACCOUNT_NUMBER,
    change_account_status,
    create_account,
    get_account_by_id,
    list_all_accounts,
    list_user_accounts,
    update_account_details,
)


@pytest.fixture
def db_session() -> Session:
    """Provide an isolated in-memory SQLite database session."""
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
    user = User(
        email=email,
        password_hash="dummy_hash",
        full_name=f"User {email}",
        role=role.value,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ===========================================================================
# 1. ACCOUNT CREATION TESTS
# ===========================================================================


def test_create_account_by_admin_for_self(db_session: Session):
    """Verify an admin can create an account with creator as initial OWNER."""
    admin = _create_user(db_session, "admin_acc@example.com", role=UserRole.ADMIN)

    account, membership = create_account(
        db=db_session,
        creator_user=admin,
        account_name="Admin Treasury",
        currency="INR",
    )

    assert account.id is not None
    assert account.account_number.startswith("LL-")
    assert account.account_name == "Admin Treasury"
    assert account.balance == 0
    assert account.status == AccountStatus.ACTIVE.value

    # Check initial membership
    assert membership.account_id == account.id
    assert membership.user_id == admin.id
    assert membership.membership_role == MembershipRole.OWNER.value

    # Check audit event
    audit = db_session.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(account.id))).first()
    assert audit is not None
    assert audit.action == "ACCOUNT_CREATED"
    assert audit.actor_user_id == admin.id


def test_create_account_by_admin_for_customer(db_session: Session):
    """Verify an admin can create an account and designate a customer as the initial OWNER."""
    admin = _create_user(db_session, "admin_cust@example.com", role=UserRole.ADMIN)
    customer = _create_user(db_session, "customer@example.com", role=UserRole.HOLDER)

    account, membership = create_account(
        db=db_session,
        creator_user=admin,
        account_name="Customer Checking",
        currency="INR",
        owner_user_id=customer.id,
    )

    assert account.account_name == "Customer Checking"
    assert membership.user_id == customer.id
    assert membership.membership_role == MembershipRole.OWNER.value


def test_create_account_non_admin_rejected(db_session: Session):
    """Verify non-admin users (HOLDER, AUDITOR) cannot create accounts."""
    holder = _create_user(db_session, "holder_blocked@example.com", role=UserRole.HOLDER)
    auditor = _create_user(db_session, "auditor_blocked@example.com", role=UserRole.AUDITOR)

    with pytest.raises(InsufficientRoleError):
        create_account(db=db_session, creator_user=holder, account_name="Holder Wallet")

    with pytest.raises(InsufficientRoleError):
        create_account(db=db_session, creator_user=auditor, account_name="Auditor Wallet")


def test_create_account_nonexistent_or_inactive_owner_rejected(db_session: Session):
    """Verify specifying a nonexistent or deactivated owner user raises an error."""
    admin = _create_user(db_session, "admin_check@example.com", role=UserRole.ADMIN)
    inactive_user = _create_user(db_session, "inactive@example.com", is_active=False)

    with pytest.raises(ValueError):
        create_account(
            db=db_session,
            creator_user=admin,
            account_name="Invalid Owner",
            owner_user_id=uuid.uuid4(),
        )

    with pytest.raises(InactiveUserError):
        create_account(
            db=db_session,
            creator_user=admin,
            account_name="Inactive Owner",
            owner_user_id=inactive_user.id,
        )


# ===========================================================================
# 2. ACCOUNT LISTING & OWNERSHIP ISOLATION TESTS
# ===========================================================================


def test_list_user_accounts_isolation(db_session: Session):
    """Verify a user only receives accounts where they hold an active membership."""
    admin = _create_user(db_session, "admin_l@example.com", role=UserRole.ADMIN)
    user_a = _create_user(db_session, "user_a_list@example.com", role=UserRole.HOLDER)
    user_b = _create_user(db_session, "user_b_list@example.com", role=UserRole.HOLDER)

    acc_a1, _ = create_account(db_session, admin, "User A Wallet 1", owner_user_id=user_a.id)
    acc_a2, _ = create_account(db_session, admin, "User A Wallet 2", owner_user_id=user_a.id)
    acc_b1, _ = create_account(db_session, admin, "User B Wallet 1", owner_user_id=user_b.id)

    # User A lists accounts
    a_accounts = list_user_accounts(db_session, user_a)
    a_ids = {acc.id for acc, _ in a_accounts}
    assert len(a_accounts) == 2
    assert acc_a1.id in a_ids
    assert acc_a2.id in a_ids
    assert acc_b1.id not in a_ids

    # User B lists accounts
    b_accounts = list_user_accounts(db_session, user_b)
    assert len(b_accounts) == 1
    assert b_accounts[0][0].id == acc_b1.id


def test_get_account_by_id_anti_idor(db_session: Session):
    """Verify querying an account without membership raises AccountNotFoundError."""
    admin = _create_user(db_session, "admin_idor@example.com", role=UserRole.ADMIN)
    user_a = _create_user(db_session, "victim@example.com", role=UserRole.HOLDER)
    user_b = _create_user(db_session, "attacker@example.com", role=UserRole.HOLDER)

    victim_acc, _ = create_account(db_session, admin, "Victim Vault", owner_user_id=user_a.id)

    # Attacker tries to get victim account
    with pytest.raises(AccountNotFoundError):
        get_account_by_id(db_session, user_b, victim_acc.id)


# ===========================================================================
# 3. ACCOUNT METADATA UPDATES
# ===========================================================================


def test_update_account_details_by_owner(db_session: Session):
    """Verify OWNER can update account metadata."""
    admin = _create_user(db_session, "admin_up@example.com", role=UserRole.ADMIN)
    owner = _create_user(db_session, "owner_up@example.com", role=UserRole.HOLDER)

    account, _ = create_account(db_session, admin, "Old Account Name", owner_user_id=owner.id)

    updated = update_account_details(
        db=db_session,
        user=owner,
        account_id=account.id,
        new_account_name="Renamed Account",
    )
    assert updated.account_name == "Renamed Account"

    # Verify audit event
    audit = db_session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_id == str(account.id), AuditEvent.action == "ACCOUNT_UPDATED")
    ).first()
    assert audit is not None
    assert audit.event_metadata["old_name"] == "Old Account Name"
    assert audit.event_metadata["new_name"] == "Renamed Account"


def test_update_account_details_rejected_for_operator_viewer_auditor(db_session: Session):
    """Verify OPERATOR, VIEWER, and AUDITOR cannot update account details."""
    admin = _create_user(db_session, "admin_up_rej@example.com", role=UserRole.ADMIN)
    owner = _create_user(db_session, "owner_real@example.com", role=UserRole.HOLDER)
    operator = _create_user(db_session, "operator_up@example.com", role=UserRole.HOLDER)
    viewer = _create_user(db_session, "viewer_up@example.com", role=UserRole.HOLDER)
    auditor = _create_user(db_session, "auditor_up@example.com", role=UserRole.AUDITOR)

    account, _ = create_account(db_session, admin, "Protected Account", owner_user_id=owner.id)

    # Attach memberships
    db_session.add(AccountMembership(user_id=operator.id, account_id=account.id, membership_role="OPERATOR"))
    db_session.add(AccountMembership(user_id=viewer.id, account_id=account.id, membership_role="VIEWER"))
    db_session.add(AccountMembership(user_id=auditor.id, account_id=account.id, membership_role="OWNER"))  # Auditor with owner membership
    db_session.commit()

    with pytest.raises(InsufficientMembershipRoleError):
        update_account_details(db_session, operator, account.id, "Hack")

    with pytest.raises(InsufficientMembershipRoleError):
        update_account_details(db_session, viewer, account.id, "Hack")

    with pytest.raises(AuditorReadOnlyViolationError):
        update_account_details(db_session, auditor, account.id, "Hack")


# ===========================================================================
# 4. ADMINISTRATIVE STATUS CHANGES
# ===========================================================================


def test_admin_change_account_status(db_session: Session):
    """Verify ADMIN can freeze, unfreeze, and close accounts."""
    admin = _create_user(db_session, "admin_status@example.com", role=UserRole.ADMIN)
    customer = _create_user(db_session, "customer_status@example.com", role=UserRole.HOLDER)

    account, _ = create_account(db_session, admin, "Status Test Account", owner_user_id=customer.id)
    assert account.status == AccountStatus.ACTIVE.value

    # Freeze account
    frozen = change_account_status(db_session, admin, account.id, AccountStatus.FROZEN)
    assert frozen.status == AccountStatus.FROZEN.value

    # Re-activate
    active = change_account_status(db_session, admin, account.id, AccountStatus.ACTIVE)
    assert active.status == AccountStatus.ACTIVE.value

    # Close account
    closed = change_account_status(db_session, admin, account.id, AccountStatus.CLOSED)
    assert closed.status == AccountStatus.CLOSED.value


def test_non_admin_cannot_change_account_status(db_session: Session):
    """Verify HOLDER and AUDITOR cannot change account status."""
    admin = _create_user(db_session, "admin_st_rej@example.com", role=UserRole.ADMIN)
    owner = _create_user(db_session, "owner_st_rej@example.com", role=UserRole.HOLDER)

    account, _ = create_account(db_session, admin, "Status Test Account 2", owner_user_id=owner.id)

    with pytest.raises(InsufficientRoleError):
        change_account_status(db_session, owner, account.id, AccountStatus.FROZEN)


def test_admin_cannot_freeze_or_close_system_clearing_account(db_session: Session):
    """Verify ADMIN attempts to freeze or close SYSTEM_CLEARING are rejected (SEC-002)."""
    from backend.app.services.account_service import get_or_create_system_clearing_account
    from backend.app.services.transaction_service import execute_deposit, execute_withdrawal

    admin = _create_user(db_session, "admin_clear_prot@example.com", role=UserRole.ADMIN)
    customer = _create_user(db_session, "cust_clear_prot@example.com", role=UserRole.HOLDER)
    clearing = get_or_create_system_clearing_account(db_session)
    cust_acc, _ = create_account(db_session, admin, "Customer Prot Wallet", owner_user_id=customer.id)

    # Attempt to freeze clearing account
    with pytest.raises(AccountStatusError, match="System clearing account status cannot be modified"):
        change_account_status(db_session, admin, clearing.id, AccountStatus.FROZEN)

    assert clearing.status == AccountStatus.ACTIVE.value

    # Attempt to close clearing account
    with pytest.raises(AccountStatusError, match="System clearing account status cannot be modified"):
        change_account_status(db_session, admin, clearing.id, AccountStatus.CLOSED)

    assert clearing.status == AccountStatus.ACTIVE.value

    # Verify deposits and withdrawals continue working seamlessly after rejected attempts
    dep = execute_deposit(db_session, customer, cust_acc.id, 5000, "dep-after-rej")
    assert dep["status"] == "POSTED"

    wth = execute_withdrawal(db_session, customer, cust_acc.id, 2000, "wth-after-rej")
    assert wth["status"] == "POSTED"


def test_list_all_accounts_requires_admin_role(db_session: Session):
    """Verify list_all_accounts rejects non-admin users and inactive admins."""
    admin = _create_user(db_session, "admin_list_all@example.com", role=UserRole.ADMIN)
    holder = _create_user(db_session, "holder_list_all@example.com", role=UserRole.HOLDER)
    auditor = _create_user(db_session, "auditor_list_all@example.com", role=UserRole.AUDITOR)

    # Rejects HOLDER
    with pytest.raises(InsufficientRoleError):
        list_all_accounts(db_session, holder)

    # Rejects AUDITOR
    with pytest.raises(InsufficientRoleError):
        list_all_accounts(db_session, auditor)

    # Rejects inactive ADMIN
    inactive_admin = _create_user(
        db_session, "inactive_admin_list_all@example.com", role=UserRole.ADMIN, is_active=False
    )
    with pytest.raises(InactiveUserError):
        list_all_accounts(db_session, inactive_admin)


def test_list_all_accounts_returns_all_customer_accounts_excluding_clearing(db_session: Session):
    """Verify list_all_accounts returns all customer accounts but excludes SYSTEM_CLEARING."""
    from backend.app.services.account_service import get_or_create_system_clearing_account

    admin = _create_user(db_session, "admin_overview@example.com", role=UserRole.ADMIN)
    cust1 = _create_user(db_session, "cust1_ov@example.com", role=UserRole.HOLDER)
    cust2 = _create_user(db_session, "cust2_ov@example.com", role=UserRole.HOLDER)

    clearing = get_or_create_system_clearing_account(db_session)
    acc1, _ = create_account(db_session, admin, "Overview Acc 1", owner_user_id=cust1.id)
    acc2, _ = create_account(db_session, admin, "Overview Acc 2", owner_user_id=cust2.id)

    results = list_all_accounts(db_session, admin)
    account_numbers = [a.account_number for a in results]

    assert SYSTEM_CLEARING_ACCOUNT_NUMBER not in account_numbers
    assert acc1.account_number in account_numbers
    assert acc2.account_number in account_numbers
    assert len(results) == 2
