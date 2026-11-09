"""
Seed demo data for LedgerLine: Admin, Account Holder, Auditor users + sample accounts.

Used exclusively for local assessment, development, and evaluation environments.
Never invoke or expose this script in production environments.
"""

import logging
import os
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from backend.app.core.database import create_app_engine, sessionmaker
from backend.app.core.security import hash_password
from backend.app.models.account import Account
from backend.app.models.account_membership import AccountMembership
from backend.app.models.user import User, UserRole
from backend.app.services.account_service import (
    create_account,
    get_or_create_system_clearing_account,
)

logger = logging.getLogger("ledgerline.seed_demo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_DEMO_PASSWORD = os.environ.get("LEDGERLINE_DEMO_PASSWORD", "SecurePass123!")

DEMO_USERS = [
    {
        "email": "admin@ledgerline.com",
        "full_name": "System Administrator",
        "role": UserRole.ADMIN,
    },
    {
        "email": "holder@ledgerline.com",
        "full_name": "Demo Account Holder",
        "role": UserRole.HOLDER,
    },
    {
        "email": "auditor@ledgerline.com",
        "full_name": "External Auditor",
        "role": UserRole.AUDITOR,
    },
]

DEMO_ACCOUNTS = [
    {
        "account_name": "Checking Account",
        "currency": "INR",
    },
    {
        "account_name": "Savings Reserve",
        "currency": "INR",
    },
]


def seed_demo_data(
    db: DbSession,
    demo_password: str = DEFAULT_DEMO_PASSWORD,
) -> dict[str, Any]:
    """Idempotently seed demo users, system clearing account, and sample customer accounts.

    Guarantees:
    - Creates Admin, Holder, Auditor users if they do not exist.
    - Uses Argon2id password hashing (no plaintext passwords in database).
    - If a user already exists, skips user creation and does not overwrite password/role.
    - Initializes the SYSTEM_CLEARING vault account via get_or_create_system_clearing_account().
    - Provisions sample customer accounts for holder@ledgerline.com using create_account().
    - If accounts already exist for the holder, skips account creation (zero duplicate accounts).
    - All created accounts have valid initial OWNER memberships and 0 starting balance
      (zero fabricated money, preserving double-entry ledger balance invariants).

    Args:
        db: Active SQLAlchemy database session.
        demo_password: Password to hash and set for newly created demo users.

    Returns:
        Dictionary summary of created and existing entities.
    """
    summary: dict[str, Any] = {
        "users_created": [],
        "users_skipped": [],
        "accounts_created": [],
        "accounts_skipped": [],
        "system_clearing_initialized": False,
    }

    # 1. Seed or retrieve users
    user_map: dict[str, User] = {}
    for user_spec in DEMO_USERS:
        email = user_spec["email"].strip().lower()
        stmt = select(User).where(User.email == email)
        existing_user = db.scalars(stmt).first()

        if existing_user is not None:
            user_map[email] = existing_user
            summary["users_skipped"].append(email)
            logger.info("User '%s' already exists (role=%s). Preserving existing credentials.", email, existing_user.role)
        else:
            hashed_pw = hash_password(demo_password)
            new_user = User(
                email=email,
                password_hash=hashed_pw,
                full_name=user_spec["full_name"],
                role=user_spec["role"].value if isinstance(user_spec["role"], UserRole) else user_spec["role"],
                is_active=True,
            )
            db.add(new_user)
            db.flush()
            user_map[email] = new_user
            summary["users_created"].append(email)
            logger.info("Created demo user '%s' with role %s.", email, new_user.role)

    # 2. Initialize SYSTEM_CLEARING account
    clearing_acc = get_or_create_system_clearing_account(db)
    summary["system_clearing_initialized"] = True
    logger.info("System clearing account verified: %s (id=%s).", clearing_acc.account_number, clearing_acc.id)

    # 3. Provision sample customer accounts for holder
    admin_user = user_map.get("admin@ledgerline.com")
    holder_user = user_map.get("holder@ledgerline.com")

    if admin_user is not None and holder_user is not None:
        # Check existing accounts where holder has OWNER membership
        existing_holder_accounts = db.scalars(
            select(Account)
            .join(AccountMembership, Account.id == AccountMembership.account_id)
            .where(AccountMembership.user_id == holder_user.id)
        ).all()
        existing_names = {acc.account_name for acc in existing_holder_accounts}

        for acc_spec in DEMO_ACCOUNTS:
            acc_name = acc_spec["account_name"]
            if acc_name in existing_names:
                summary["accounts_skipped"].append(acc_name)
                logger.info("Account '%s' already exists for holder. Skipping creation.", acc_name)
            else:
                account, membership = create_account(
                    db=db,
                    creator_user=admin_user,
                    account_name=acc_name,
                    currency=acc_spec["currency"],
                    owner_user_id=holder_user.id,
                )
                summary["accounts_created"].append(
                    {
                        "id": str(account.id),
                        "account_number": account.account_number,
                        "account_name": account.account_name,
                        "owner_id": str(holder_user.id),
                    }
                )
                logger.info(
                    "Created sample account '%s' (%s) owned by %s.",
                    account.account_name,
                    account.account_number,
                    holder_user.email,
                )

    db.commit()
    logger.info(
        "Demo seed completed. Users created: %d, Accounts created: %d.",
        len(summary["users_created"]),
        len(summary["accounts_created"]),
    )
    return summary


def main() -> None:
    """Command-line entry point for manual local evaluation demo seeding."""
    print("=" * 70)
    print(" LedgerLine — Demo Data Seed Script (Local Evaluation Only)")
    print("=" * 70)
    print("WARNING: This script provisions evaluation accounts with known demo")
    print("credentials. NEVER run this in a production deployment.")
    print("=" * 70)

    engine = create_app_engine()
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with SessionLocal() as db:
        try:
            summary = seed_demo_data(db)
            print("\nSeeding completed successfully:")
            print(f"- Users created: {summary['users_created']}")
            print(f"- Users skipped (already present): {summary['users_skipped']}")
            print(f"- Accounts created: {[a['account_name'] for a in summary['accounts_created']]}")
            print(f"- Accounts skipped: {summary['accounts_skipped']}")
            print("\nDemo login credentials:")
            print(f"  Admin:          admin@ledgerline.com   / {DEFAULT_DEMO_PASSWORD}")
            print(f"  Account Holder: holder@ledgerline.com  / {DEFAULT_DEMO_PASSWORD}")
            print(f"  Auditor:        auditor@ledgerline.com / {DEFAULT_DEMO_PASSWORD}")
        except Exception as exc:
            db.rollback()
            print(f"\n[ERROR] Seeding failed: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
