"""
Unit tests for LedgerLine demo data provisioning script (seed_demo.py).

Verifies:
- Creation of 3 demo users (Admin, Holder, Auditor) with exact roles and Argon2id password hashes.
- Idempotency: multiple executions produce no duplicates and skip already-created entities.
- Non-destructive behaviour: existing user passwords and roles are not modified or overwritten.
- System clearing account initialization.
- Sample customer accounts created for the demo holder with 0 balance and valid OWNER membership.
- Authentication integration: authenticate_user succeeds with seeded credentials.
"""

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.security import hash_password, verify_password
from backend.app.models.account import Account
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.base import Base
from backend.app.models.user import User, UserRole
from backend.app.scripts.seed_demo import seed_demo_data
from backend.app.services.account_service import SYSTEM_CLEARING_ACCOUNT_NUMBER
from backend.app.services.auth_service import authenticate_user


@pytest.fixture
def db_session():
    """Isolated in-memory SQLite session for testing seed_demo."""
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


def test_seed_demo_data_creates_all_demo_users_and_accounts(db_session: Session):
    """Verify seed_demo_data creates Admin, Holder, Auditor users and sample accounts."""
    summary = seed_demo_data(db_session, demo_password="TestPassword123!")

    assert len(summary["users_created"]) == 3
    assert set(summary["users_created"]) == {
        "admin@ledgerline.com",
        "holder@ledgerline.com",
        "auditor@ledgerline.com",
    }
    assert summary["system_clearing_initialized"] is True
    assert len(summary["accounts_created"]) == 2

    # Check user roles and Argon2id hash validity
    admin = db_session.scalars(select(User).where(User.email == "admin@ledgerline.com")).first()
    assert admin is not None
    assert admin.role == UserRole.ADMIN.value
    assert admin.is_active is True
    assert verify_password("TestPassword123!", admin.password_hash)

    holder = db_session.scalars(select(User).where(User.email == "holder@ledgerline.com")).first()
    assert holder is not None
    assert holder.role == UserRole.HOLDER.value
    assert holder.is_active is True
    assert verify_password("TestPassword123!", holder.password_hash)

    auditor = db_session.scalars(select(User).where(User.email == "auditor@ledgerline.com")).first()
    assert auditor is not None
    assert auditor.role == UserRole.AUDITOR.value
    assert auditor.is_active is True
    assert verify_password("TestPassword123!", auditor.password_hash)

    # Check SYSTEM_CLEARING account exists and balance is 0
    clearing = db_session.scalars(
        select(Account).where(Account.account_number == SYSTEM_CLEARING_ACCOUNT_NUMBER)
    ).first()
    assert clearing is not None
    assert clearing.balance == 0

    # Check sample customer accounts
    holder_memberships = db_session.scalars(
        select(AccountMembership).where(AccountMembership.user_id == holder.id)
    ).all()
    assert len(holder_memberships) == 2
    for m in holder_memberships:
        assert m.membership_role == MembershipRole.OWNER.value
        assert m.account.balance == 0
        assert m.account.currency == "INR"

    account_names = {m.account.account_name for m in holder_memberships}
    assert account_names == {"Checking Account", "Savings Reserve"}


def test_seed_demo_data_is_idempotent(db_session: Session):
    """Verify running seed_demo_data repeatedly does not create duplicate users or accounts."""
    first_run = seed_demo_data(db_session, demo_password="FirstRunPassword123!")
    assert len(first_run["users_created"]) == 3
    assert len(first_run["accounts_created"]) == 2

    # Second run
    second_run = seed_demo_data(db_session, demo_password="SecondRunPassword123!")
    assert len(second_run["users_created"]) == 0
    assert set(second_run["users_skipped"]) == {
        "admin@ledgerline.com",
        "holder@ledgerline.com",
        "auditor@ledgerline.com",
    }
    assert len(second_run["accounts_created"]) == 0
    assert set(second_run["accounts_skipped"]) == {"Checking Account", "Savings Reserve"}

    # Total counts in DB should still be exactly 3 users and 2 customer accounts (+1 clearing)
    all_users = db_session.scalars(select(User)).all()
    assert len(all_users) == 3

    all_accounts = db_session.scalars(select(Account)).all()
    assert len(all_accounts) == 3  # 2 customer + 1 clearing


def test_seed_demo_data_preserves_existing_user_credentials(db_session: Session):
    """Verify seed_demo_data does not overwrite existing users' passwords or roles."""
    custom_hash = hash_password("MyCustomPassword999!")
    existing_admin = User(
        email="admin@ledgerline.com",
        password_hash=custom_hash,
        full_name="Custom Admin",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db_session.add(existing_admin)
    db_session.commit()

    summary = seed_demo_data(db_session, demo_password="DifferentPassword123!")
    assert "admin@ledgerline.com" in summary["users_skipped"]
    assert "admin@ledgerline.com" not in summary["users_created"]

    # Verify admin password remains untouched
    admin_after = db_session.scalars(select(User).where(User.email == "admin@ledgerline.com")).first()
    assert admin_after.password_hash == custom_hash
    assert verify_password("MyCustomPassword999!", admin_after.password_hash)
    assert not verify_password("DifferentPassword123!", admin_after.password_hash)


def test_seed_demo_credentials_authenticate_successfully(db_session: Session):
    """Verify seeded credentials authenticate via authenticate_user service."""
    seed_demo_data(db_session, demo_password="SecurePass123!")

    for email, expected_role in [
        ("admin@ledgerline.com", UserRole.ADMIN),
        ("holder@ledgerline.com", UserRole.HOLDER),
        ("auditor@ledgerline.com", UserRole.AUDITOR),
    ]:
        user = authenticate_user(db_session, email, "SecurePass123!")
        assert user.role == expected_role.value
