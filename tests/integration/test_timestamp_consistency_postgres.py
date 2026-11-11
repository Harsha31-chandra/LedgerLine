"""
PostgreSQL integration tests for database-enforced timestamp consistency.

Verifies:
- Direct SQL UPDATE triggers refresh of updated_at on mutable tables (accounts, users, transactions).
- SQLAlchemy ORM updates follow the identical timestamp policy.
- created_at is strictly preserved and cannot be tampered with on UPDATE.
- Timestamps are timezone-aware (TIMESTAMPTZ / UTC).
- No-op updates preserve existing updated_at without spurious timestamp bumps.
- Server-side clock_timestamp() overrides any client-supplied forged updated_at.
- Trigger function update_updated_at_column is owned by ledgerline_migrator.
- Runtime application role ledgerline_app cannot disable or drop timestamp triggers.
- Immutable tables (ledger_entries, audit_events) are strictly excluded from timestamp triggers.
- Existing ledger immutability protections (UPDATE/DELETE/TRUNCATE denial) remain completely intact.
"""

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.security import hash_password
from backend.app.models.account import Account, AccountStatus
from backend.app.models.transaction import Transaction, TransactionStatus, TransactionType
from backend.app.models.user import User, UserRole

pytestmark = pytest.mark.anyio


def _clean_test_records(engine: Engine, user_ids: list[uuid.UUID], account_ids: list[uuid.UUID], tx_ids: list[uuid.UUID]) -> None:
    """Helper to cleanly remove test probe rows using table owner engine."""
    with engine.begin() as conn:
        if tx_ids:
            conn.execute(text("DELETE FROM transactions WHERE id = ANY(:ids);"), {"ids": tx_ids})
        if account_ids:
            conn.execute(text("DELETE FROM accounts WHERE id = ANY(:ids);"), {"ids": account_ids})
        if user_ids:
            conn.execute(text("DELETE FROM users WHERE id = ANY(:ids);"), {"ids": user_ids})


def test_01_raw_sql_update_refreshes_account_updated_at(test_engine: Engine, app_test_engine: Engine):
    """1. Verify direct SQL UPDATE on accounts automatically advances updated_at and preserves created_at."""
    acc_id = uuid.uuid4()
    acc_num = f"ACC_TS_{acc_id.hex[:8].upper()}"

    with test_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, account_number, account_name, currency, balance, status, created_at, updated_at) "
                "VALUES (:id, :num, :name, 'INR', 10000, 'ACTIVE', clock_timestamp(), clock_timestamp());"
            ),
            {"id": acc_id, "num": acc_num, "name": "Initial Name"},
        )

    try:
        # Read initial timestamps
        with app_test_engine.connect() as conn:
            row_before = conn.execute(
                text("SELECT created_at, updated_at, account_name FROM accounts WHERE id = :id;"),
                {"id": acc_id},
            ).mappings().one()

        t_created = row_before["created_at"]
        t_updated_1 = row_before["updated_at"]

        assert t_created.tzinfo is not None, "created_at must be timezone-aware"
        assert t_updated_1.tzinfo is not None, "updated_at must be timezone-aware"

        # Direct SQL UPDATE via runtime application role
        with app_test_engine.begin() as conn:
            conn.execute(
                text("UPDATE accounts SET account_name = :name WHERE id = :id;"),
                {"id": acc_id, "name": "Direct SQL Updated Name"},
            )

        # Verify updated_at advanced and created_at was strictly preserved
        with app_test_engine.connect() as conn:
            row_after = conn.execute(
                text("SELECT created_at, updated_at, account_name FROM accounts WHERE id = :id;"),
                {"id": acc_id},
            ).mappings().one()

        assert row_after["account_name"] == "Direct SQL Updated Name"
        assert row_after["created_at"] == t_created, "created_at must remain unchanged"
        assert row_after["updated_at"] > t_updated_1, "updated_at must advance on raw SQL UPDATE"
        assert row_after["updated_at"].tzinfo is not None
    finally:
        _clean_test_records(test_engine, [], [acc_id], [])


def test_02_sqlalchemy_update_refreshes_account_updated_at(test_engine: Engine, app_test_engine: Engine):
    """2. Verify SQLAlchemy ORM update produces identical timestamp advancement."""
    acc_id = uuid.uuid4()
    acc_num = f"ACC_TS_{acc_id.hex[:8].upper()}"

    SessionFactory = sessionmaker(bind=app_test_engine, autocommit=False, autoflush=False)
    session: Session = SessionFactory()

    try:
        account = Account(
            id=acc_id,
            account_number=acc_num,
            account_name="ORM Initial Name",
            currency="INR",
            balance=5000,
            status=AccountStatus.ACTIVE.value,
        )
        session.add(account)
        session.commit()

        initial_created = account.created_at
        initial_updated = account.updated_at
        assert initial_created.tzinfo is not None
        assert initial_updated.tzinfo is not None

        # Update via SQLAlchemy ORM
        account.account_name = "ORM Renamed Account"
        session.commit()
        session.refresh(account)

        assert account.account_name == "ORM Renamed Account"
        assert account.created_at == initial_created, "created_at must be preserved under ORM update"
        assert account.updated_at > initial_updated, "updated_at must advance under ORM update"
    finally:
        session.close()
        _clean_test_records(test_engine, [], [acc_id], [])


def test_03_user_and_transaction_raw_sql_updates_refresh_updated_at(test_engine: Engine, app_test_engine: Engine):
    """3. Verify direct SQL UPDATE on users and transactions triggers timestamp updates."""
    user_id = uuid.uuid4()
    email = f"user_ts_{user_id.hex[:6]}@ledgerline.com"
    tx_id = uuid.uuid4()
    tx_ref = f"TX_TS_{tx_id.hex[:8].upper()}"

    with test_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role, is_active, created_at, updated_at) "
                "VALUES (:id, :email, :pwd, :name, 'HOLDER', true, clock_timestamp(), clock_timestamp());"
            ),
            {"id": user_id, "email": email, "pwd": hash_password("ValidPassword123!"), "name": "Initial User"},
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, reference, transaction_type, status, amount_paise, currency, created_at, updated_at) "
                "VALUES (:id, :ref, 'DEPOSIT', 'PENDING', 25000, 'INR', clock_timestamp(), clock_timestamp());"
            ),
            {"id": tx_id, "ref": tx_ref},
        )

    try:
        # Read initial timestamps
        with app_test_engine.connect() as conn:
            u_before = conn.execute(
                text("SELECT created_at, updated_at, full_name FROM users WHERE id = :id;"),
                {"id": user_id},
            ).mappings().one()
            t_before = conn.execute(
                text("SELECT created_at, updated_at, status FROM transactions WHERE id = :id;"),
                {"id": tx_id},
            ).mappings().one()

        # Update users via raw SQL
        with app_test_engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET full_name = 'Updated User Full Name' WHERE id = :id;"),
                {"id": user_id},
            )

        # Update transactions via raw SQL
        with app_test_engine.begin() as conn:
            conn.execute(
                text("UPDATE transactions SET status = 'POSTED' WHERE id = :id;"),
                {"id": tx_id},
            )

        # Verify users updated_at advanced
        with app_test_engine.connect() as conn:
            u_after = conn.execute(
                text("SELECT created_at, updated_at, full_name FROM users WHERE id = :id;"),
                {"id": user_id},
            ).mappings().one()
            t_after = conn.execute(
                text("SELECT created_at, updated_at, status FROM transactions WHERE id = :id;"),
                {"id": tx_id},
            ).mappings().one()

        assert u_after["full_name"] == "Updated User Full Name"
        assert u_after["created_at"] == u_before["created_at"]
        assert u_after["updated_at"] > u_before["updated_at"]

        assert t_after["status"] == "POSTED"
        assert t_after["created_at"] == t_before["created_at"]
        assert t_after["updated_at"] > t_before["updated_at"]
    finally:
        _clean_test_records(test_engine, [user_id], [], [tx_id])


def test_04_no_op_update_preserves_existing_updated_at(test_engine: Engine, app_test_engine: Engine):
    """4. Verify that a no-op UPDATE (identical row values) does not modify updated_at."""
    acc_id = uuid.uuid4()
    acc_num = f"ACC_NOOP_{acc_id.hex[:8].upper()}"

    with test_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, account_number, account_name, currency, balance, status, created_at, updated_at) "
                "VALUES (:id, :num, 'Static Name', 'INR', 10000, 'ACTIVE', clock_timestamp(), clock_timestamp());"
            ),
            {"id": acc_id, "num": acc_num},
        )

    try:
        with app_test_engine.connect() as conn:
            row_initial = conn.execute(
                text("SELECT updated_at FROM accounts WHERE id = :id;"),
                {"id": acc_id},
            ).mappings().one()

        t_initial = row_initial["updated_at"]

        # Execute no-op UPDATE setting identical values
        with app_test_engine.begin() as conn:
            conn.execute(
                text("UPDATE accounts SET account_name = 'Static Name' WHERE id = :id;"),
                {"id": acc_id},
            )

        with app_test_engine.connect() as conn:
            row_after_noop = conn.execute(
                text("SELECT updated_at FROM accounts WHERE id = :id;"),
                {"id": acc_id},
            ).mappings().one()

        # Timestamp must be identical because no row data was modified
        assert row_after_noop["updated_at"] == t_initial, "No-op UPDATE must not bump updated_at"
    finally:
        _clean_test_records(test_engine, [], [acc_id], [])


def test_05_created_at_tampering_is_prevented_by_trigger(test_engine: Engine, app_test_engine: Engine):
    """5. Verify that attempting to modify created_at on UPDATE is prevented by the trigger."""
    acc_id = uuid.uuid4()
    acc_num = f"ACC_TAMP_{acc_id.hex[:8].upper()}"

    with test_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, account_number, account_name, currency, balance, status, created_at, updated_at) "
                "VALUES (:id, :num, 'Name Before', 'INR', 10000, 'ACTIVE', clock_timestamp(), clock_timestamp());"
            ),
            {"id": acc_id, "num": acc_num},
        )

    try:
        with app_test_engine.connect() as conn:
            row_before = conn.execute(
                text("SELECT created_at, updated_at FROM accounts WHERE id = :id;"),
                {"id": acc_id},
            ).mappings().one()

        t_original_created = row_before["created_at"]
        t_original_updated = row_before["updated_at"]

        # Attempt to modify created_at to an ancient date while updating account_name
        with app_test_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE accounts SET created_at = '1970-01-01 00:00:00+00', account_name = 'Name After' "
                    "WHERE id = :id;"
                ),
                {"id": acc_id},
            )

        with app_test_engine.connect() as conn:
            row_after = conn.execute(
                text("SELECT created_at, updated_at, account_name FROM accounts WHERE id = :id;"),
                {"id": acc_id},
            ).mappings().one()

        assert row_after["account_name"] == "Name After"
        assert row_after["created_at"] == t_original_created, "created_at tampering must be strictly blocked"
        assert row_after["updated_at"] > t_original_updated, "updated_at must advance"
    finally:
        _clean_test_records(test_engine, [], [acc_id], [])


def test_06_updated_at_tampering_is_overridden_by_server_clock(test_engine: Engine, app_test_engine: Engine):
    """6. Verify that an explicit client-supplied updated_at is overridden by server clock_timestamp()."""
    acc_id = uuid.uuid4()
    acc_num = f"ACC_FORGE_{acc_id.hex[:8].upper()}"

    with test_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, account_number, account_name, currency, balance, status, created_at, updated_at) "
                "VALUES (:id, :num, 'Original Name', 'INR', 10000, 'ACTIVE', clock_timestamp(), clock_timestamp());"
            ),
            {"id": acc_id, "num": acc_num},
        )

    try:
        with app_test_engine.connect() as conn:
            row_before = conn.execute(
                text("SELECT updated_at FROM accounts WHERE id = :id;"),
                {"id": acc_id},
            ).mappings().one()

        t_before = row_before["updated_at"]

        # Attempt to set updated_at to a forged past timestamp
        forged_time = "1999-12-31 23:59:59+00"
        with app_test_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE accounts SET updated_at = :forged, account_name = 'New Value' "
                    "WHERE id = :id;"
                ),
                {"id": acc_id, "forged": forged_time},
            )

        with app_test_engine.connect() as conn:
            row_after = conn.execute(
                text("SELECT updated_at FROM accounts WHERE id = :id;"),
                {"id": acc_id},
            ).mappings().one()

        # The forged time must NOT be present; server clock_timestamp() must override
        assert row_after["updated_at"].year >= 2026, "Forged timestamp must be replaced with server clock"
        assert row_after["updated_at"] > t_before, "Server updated_at must advance"
    finally:
        _clean_test_records(test_engine, [], [acc_id], [])


def test_07_timestamp_trigger_and_function_ownership(test_engine: Engine):
    """7. Verify trigger function and triggers are owned by ledgerline_migrator."""
    with test_engine.connect() as conn:
        # Function owner
        func_owner = conn.execute(
            text(
                "SELECT pg_get_userbyid(proowner) FROM pg_proc JOIN pg_namespace n ON pg_proc.pronamespace = n.oid "
                "WHERE n.nspname = 'public' AND proname = 'update_updated_at_column';"
            )
        ).scalar()
        assert func_owner == "ledgerline_migrator", "Function must be owned by ledgerline_migrator"

        # Triggers on mutable tables
        expected_triggers = {
            ("accounts", "trg_accounts_updated_at"),
            ("users", "trg_users_updated_at"),
            ("transactions", "trg_transactions_updated_at"),
        }
        rows = conn.execute(
            text(
                "SELECT event_object_table, trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema = 'public' AND trigger_name LIKE 'trg_%_updated_at';"
            )
        ).fetchall()
        actual_triggers = {(r[0], r[1]) for r in rows}
        assert expected_triggers == actual_triggers, f"Expected triggers {expected_triggers}, got {actual_triggers}"


def test_08_runtime_role_cannot_tamper_with_timestamp_triggers(app_test_engine: Engine):
    """8. Verify that runtime role ledgerline_app cannot disable, drop, or alter timestamp triggers."""
    # Attempt disable trigger on accounts
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("ALTER TABLE accounts DISABLE TRIGGER trg_accounts_updated_at;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"
        assert "must be owner of table accounts" in str(err).lower()

    # Attempt drop trigger on accounts
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("DROP TRIGGER trg_accounts_updated_at ON accounts;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"

    # Attempt drop trigger function
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("DROP FUNCTION update_updated_at_column();"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_09_immutable_tables_excluded_and_ledger_immutability_intact(test_engine: Engine, app_test_engine: Engine):
    """9. Verify immutable tables have no update triggers and ledger UPDATE/DELETE/TRUNCATE remains denied."""
    with test_engine.connect() as conn:
        # Verify ledger_entries has NO trg_*_updated_at trigger
        ledger_ts_triggers = conn.execute(
            text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema = 'public' AND event_object_table = 'ledger_entries' "
                "AND trigger_name LIKE '%updated_at%';"
            )
        ).fetchall()
        assert len(ledger_ts_triggers) == 0, "ledger_entries must NOT have updated_at trigger"

        # Verify audit_events has NO updated_at trigger
        audit_ts_triggers = conn.execute(
            text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema = 'public' AND event_object_table = 'audit_events' "
                "AND trigger_name LIKE '%updated_at%';"
            )
        ).fetchall()
        assert len(audit_ts_triggers) == 0, "audit_events must NOT have updated_at trigger"

    # Verify ledger_entries still strictly blocks UPDATE/DELETE/TRUNCATE
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("UPDATE ledger_entries SET amount_paise = 1;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) in ("20000", "42501")

    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("DELETE FROM ledger_entries;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) in ("20000", "42501")

    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("TRUNCATE TABLE ledger_entries;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) in ("20000", "42501")
