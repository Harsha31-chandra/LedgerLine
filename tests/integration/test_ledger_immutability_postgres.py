"""
Integration tests verifying PostgreSQL database-level ledger immutability and role separation.

Target: Isolated PostgreSQL test database (ledgerline_test).
Validates:
1. Legitimate ledger INSERT succeeds.
2. Direct SQL UPDATE fails.
3. Direct SQL DELETE fails.
4. TRUNCATE fails.
5. Rejected operations leave original records unchanged.
6. The ordinary application role cannot grant itself maintenance privileges.
7. The ordinary application role cannot disable triggers.
8. The ordinary application role cannot change ledger table ownership.
9. The ordinary application role cannot obtain superuser privileges.
10. Existing deposit, withdrawal, and transfer operations still succeed.
11. Existing ledger reconciliation remains correct.
12. Test cleanup works using the approved isolated test-administration mechanism.
"""

import uuid
from typing import Generator

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.security import hash_password
from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.audit_event import AuditEvent
from backend.app.models.idempotency import IdempotencyRecord
from backend.app.models.ledger_entry import EntryType, LedgerEntry
from backend.app.models.transaction import Transaction, TransactionStatus, TransactionType
from backend.app.models.user import User, UserRole
from backend.app.services.account_service import get_or_create_system_clearing_account
from backend.app.services.transaction_service import (
    execute_deposit,
    execute_transfer,
    execute_withdrawal,
)


def _cleanup_test_records(test_engine: Engine, user_ids: list[uuid.UUID], account_ids: list[uuid.UUID]) -> None:
    """Isolated test-admin cleanup mechanism.

    Connects via the test database owner (ledgerline) to safely delete test fixture records.
    Disables trg_ledger_entries_immutability only during fixture removal, then guarantees re-enabling.
    Ordinary application roles (ledgerline_app) cannot execute this because they do not own the table.
    """
    with test_engine.begin() as conn:
        if conn.dialect.name != "postgresql":
            return

        # 1. Collect transaction IDs associated with test users
        tx_query = select(Transaction.id).where(
            Transaction.initiated_by.in_(user_ids) if user_ids else text("false")
        )
        tx_ids = [row[0] for row in conn.execute(tx_query).fetchall()]

        # 2. Collect ledger entries referencing these transactions or accounts
        le_conditions = []
        if tx_ids:
            le_conditions.append(LedgerEntry.transaction_id.in_(tx_ids))
        if account_ids:
            le_conditions.append(LedgerEntry.account_id.in_(account_ids))

        # 3. Disable immutability trigger via table-owner DDL, delete test entries, re-enable
        trigger_disabled = False
        try:
            has_trigger = conn.execute(
                text("SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ledger_entries_immutability'")
            ).scalar() is not None
            if has_trigger:
                conn.execute(text("ALTER TABLE ledger_entries DISABLE TRIGGER trg_ledger_entries_immutability;"))
                trigger_disabled = True

            if le_conditions:
                from sqlalchemy import or_
                conn.execute(delete(LedgerEntry).where(or_(*le_conditions)))
        finally:
            if trigger_disabled:
                conn.execute(text("ALTER TABLE ledger_entries ENABLE TRIGGER trg_ledger_entries_immutability;"))

        # 4. Clean remaining test fixtures
        if tx_ids:
            conn.execute(delete(Transaction).where(Transaction.id.in_(tx_ids)))
        if account_ids:
            conn.execute(delete(AccountMembership).where(AccountMembership.account_id.in_(account_ids)))
            conn.execute(delete(Account).where(Account.id.in_(account_ids)))
        if user_ids:
            conn.execute(delete(AccountMembership).where(AccountMembership.user_id.in_(user_ids)))
            conn.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id.in_(user_ids)))
            conn.execute(delete(AuditEvent).where(AuditEvent.actor_user_id.in_(user_ids)))
            conn.execute(delete(User).where(User.id.in_(user_ids)))


@pytest.fixture
def immutability_fixture(test_engine: Engine) -> Generator[dict, None, None]:
    """Create isolated test user, account, and initial transaction fixtures."""
    session_factory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = session_factory()

    created_user_ids: list[uuid.UUID] = []
    created_account_ids: list[uuid.UUID] = []

    try:
        user = User(
            id=uuid.uuid4(),
            email=f"immut_{uuid.uuid4().hex[:8]}@ledgerline.com",
            password_hash=hash_password("ValidPassword123!"),
            full_name="Immutability Tester",
            role=UserRole.HOLDER.value,
            is_active=True,
        )
        session.add(user)
        session.flush()

        account = Account(
            id=uuid.uuid4(),
            account_number=f"IMMUT-{uuid.uuid4().hex[:8].upper()}",
            account_name="Immutability Test Account",
            balance=50000,
            currency="INR",
            status=AccountStatus.ACTIVE.value,
        )
        session.add(account)
        session.flush()

        membership = AccountMembership(
            id=uuid.uuid4(),
            user_id=user.id,
            account_id=account.id,
            membership_role=MembershipRole.OWNER.value,
        )
        session.add(membership)
        session.flush()

        tx = Transaction(
            id=uuid.uuid4(),
            reference=f"TX-IMMUT-{uuid.uuid4().hex[:8]}",
            transaction_type=TransactionType.DEPOSIT.value,
            status=TransactionStatus.POSTED.value,
            amount_paise=50000,
            currency="INR",
            description="Initial fixture deposit",
            initiated_by=user.id,
        )
        session.add(tx)
        session.flush()

        entry = LedgerEntry(
            id=uuid.uuid4(),
            account_id=account.id,
            transaction_id=tx.id,
            entry_type=EntryType.CREDIT.value,
            amount_paise=50000,
        )
        session.add(entry)
        session.commit()

        created_user_ids.append(user.id)
        created_account_ids.append(account.id)

        fixture_data = {
            "user_id": user.id,
            "account_id": account.id,
            "transaction_id": tx.id,
            "entry_id": entry.id,
        }
        yield fixture_data

    finally:
        session.close()
        _cleanup_test_records(test_engine, created_user_ids, created_account_ids)


def test_01_legitimate_ledger_insert_succeeds(immutability_fixture: dict, app_test_engine: Engine, test_engine: Engine):
    """1. Verify that legitimate INSERT into ledger_entries succeeds for both runtime and admin roles."""
    entry_id_owner = uuid.uuid4()
    entry_id_app = uuid.uuid4()

    # Insert under table owner (ledgerline) via direct SQL
    with test_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ledger_entries (id, account_id, transaction_id, entry_type, amount_paise)
                VALUES (:id, :acc_id, :tx_id, 'CREDIT', 1000);
                """
            ),
            {
                "id": entry_id_owner,
                "acc_id": immutability_fixture["account_id"],
                "tx_id": immutability_fixture["transaction_id"],
            },
        )
        res = conn.execute(select(LedgerEntry.amount_paise).where(LedgerEntry.id == entry_id_owner)).scalar()
        assert res == 1000

    # Insert under runtime application user (ledgerline_app) via direct SQL
    with app_test_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ledger_entries (id, account_id, transaction_id, entry_type, amount_paise)
                VALUES (:id, :acc_id, :tx_id, 'CREDIT', 2000);
                """
            ),
            {
                "id": entry_id_app,
                "acc_id": immutability_fixture["account_id"],
                "tx_id": immutability_fixture["transaction_id"],
            },
        )
        res = conn.execute(select(LedgerEntry.amount_paise).where(LedgerEntry.id == entry_id_app)).scalar()
        assert res == 2000


def test_02_direct_sql_update_fails(immutability_fixture: dict, test_engine: Engine, app_test_engine: Engine):
    """2. Verify that direct SQL UPDATE on ledger_entries fails with appropriate exceptions."""
    entry_id = immutability_fixture["entry_id"]

    # Table owner attempt: blocked by trg_ledger_entries_immutability trigger raising SQLSTATE 20000
    with test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(
                text("UPDATE ledger_entries SET amount_paise = 999999 WHERE id = :id"),
                {"id": entry_id},
            )
        err = exc_info.value
        assert "Financial ledger entries are strictly immutable: UPDATE is prohibited" in str(err)
        assert getattr(err.orig, "pgcode", None) == "20000"

    # Runtime app role attempt: blocked by PostgreSQL privilege check (no UPDATE granted)
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(
                text("UPDATE ledger_entries SET amount_paise = 999999 WHERE id = :id"),
                {"id": entry_id},
            )
        err = exc_info.value
        assert "permission denied for table ledger_entries" in str(err).lower()
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_03_direct_sql_delete_fails(immutability_fixture: dict, test_engine: Engine, app_test_engine: Engine):
    """3. Verify that direct SQL DELETE on ledger_entries fails with appropriate exceptions."""
    entry_id = immutability_fixture["entry_id"]

    # Table owner attempt: blocked by trg_ledger_entries_immutability trigger raising SQLSTATE 20000
    with test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(
                text("DELETE FROM ledger_entries WHERE id = :id"),
                {"id": entry_id},
            )
        err = exc_info.value
        assert "Financial ledger entries are strictly immutable: DELETE is prohibited" in str(err)
        assert getattr(err.orig, "pgcode", None) == "20000"

    # Runtime app role attempt: blocked by PostgreSQL privilege check (no DELETE granted)
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(
                text("DELETE FROM ledger_entries WHERE id = :id"),
                {"id": entry_id},
            )
        err = exc_info.value
        assert "permission denied for table ledger_entries" in str(err).lower()
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_04_truncate_fails(test_engine: Engine, app_test_engine: Engine):
    """4. Verify that statement-level TRUNCATE on ledger_entries fails."""
    # Table owner attempt: blocked by trg_ledger_entries_truncate trigger raising SQLSTATE 20000
    with test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("TRUNCATE TABLE ledger_entries;"))
        err = exc_info.value
        assert "Financial ledger entries are strictly immutable: TRUNCATE is prohibited" in str(err)
        assert getattr(err.orig, "pgcode", None) == "20000"

    # Runtime app role attempt: blocked by PostgreSQL privilege check (no TRUNCATE granted)
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("TRUNCATE TABLE ledger_entries;"))
        err = exc_info.value
        assert "permission denied for table ledger_entries" in str(err).lower()
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_05_rejected_operations_leave_original_records_unchanged(
    immutability_fixture: dict, test_engine: Engine, app_test_engine: Engine
):
    """5. Verify that rejected UPDATE and DELETE attempts leave historical records bit-for-bit unchanged."""
    entry_id = immutability_fixture["entry_id"]

    # Read original record state
    with test_engine.connect() as conn:
        orig = conn.execute(
            text("SELECT id, account_id, transaction_id, entry_type, amount_paise FROM ledger_entries WHERE id = :id"),
            {"id": entry_id},
        ).fetchone()
        assert orig is not None
        orig_dict = {
            "id": orig[0],
            "account_id": orig[1],
            "transaction_id": orig[2],
            "entry_type": orig[3],
            "amount_paise": orig[4],
        }

    # Attempt malicious UPDATE and DELETE from runtime app role
    for query in [
        text("UPDATE ledger_entries SET amount_paise = 999999 WHERE id = :id"),
        text("DELETE FROM ledger_entries WHERE id = :id"),
    ]:
        with app_test_engine.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(query, {"id": entry_id})

    # Attempt malicious UPDATE and DELETE from table owner
    for query in [
        text("UPDATE ledger_entries SET amount_paise = 999999 WHERE id = :id"),
        text("DELETE FROM ledger_entries WHERE id = :id"),
    ]:
        with test_engine.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(query, {"id": entry_id})

    # Verify that the record is completely intact and matches original data
    with test_engine.connect() as conn:
        current = conn.execute(
            text("SELECT id, account_id, transaction_id, entry_type, amount_paise FROM ledger_entries WHERE id = :id"),
            {"id": entry_id},
        ).fetchone()
        assert current is not None
        current_dict = {
            "id": current[0],
            "account_id": current[1],
            "transaction_id": current[2],
            "entry_type": current[3],
            "amount_paise": current[4],
        }
        assert orig_dict == current_dict


def test_06_app_role_cannot_grant_itself_maintenance_privileges(app_test_engine: Engine):
    """6. Verify that the runtime role ledgerline_app cannot grant itself privileges on ledger_entries."""
    # Attempt to grant superuser role to self -> explicitly fails with permission denied
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("GRANT ledgerline TO ledgerline_app;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"

    # In a separate connection, attempt to grant table privileges to self without grant option
    # PostgreSQL issues a warning and refuses to grant privileges
    with app_test_engine.connect() as conn:
        conn.execute(text("GRANT UPDATE, DELETE ON ledger_entries TO ledgerline_app;"))
        can_update = conn.execute(text("SELECT has_table_privilege('ledgerline_app', 'ledger_entries', 'UPDATE')")).scalar()
        can_delete = conn.execute(text("SELECT has_table_privilege('ledgerline_app', 'ledger_entries', 'DELETE')")).scalar()
        assert can_update is False
        assert can_delete is False


def test_07_app_role_cannot_disable_triggers(app_test_engine: Engine):
    """7. Verify that the runtime role ledgerline_app cannot disable the immutability trigger."""
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("ALTER TABLE ledger_entries DISABLE TRIGGER trg_ledger_entries_immutability;"))
        err = exc_info.value
        assert "must be owner of table ledger_entries" in str(err).lower()
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_08_app_role_cannot_change_table_ownership(app_test_engine: Engine):
    """8. Verify that the runtime role ledgerline_app cannot alter ledger table ownership."""
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("ALTER TABLE ledger_entries OWNER TO ledgerline_app;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_09_app_role_cannot_obtain_superuser_privileges(app_test_engine: Engine):
    """9. Verify that the runtime role ledgerline_app cannot alter its own role to superuser."""
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("ALTER ROLE ledgerline_app SUPERUSER;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_10_financial_workflows_succeed_under_runtime_role(test_engine: Engine, app_test_engine: Engine):
    """10. Verify that deposit, withdrawal, and transfer services succeed under runtime database operations."""
    session_factory = sessionmaker(bind=app_test_engine, autocommit=False, autoflush=False)
    session = session_factory()

    created_user_ids: list[uuid.UUID] = []
    created_account_ids: list[uuid.UUID] = []

    try:
        # Create users and accounts via table-owner session first
        admin_session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)()
        try:
            get_or_create_system_clearing_account(admin_session)

            user_a = User(
                id=uuid.uuid4(),
                email=f"user_a_{uuid.uuid4().hex[:6]}@ledgerline.com",
                password_hash=hash_password("ValidPassword123!"),
                full_name="User Alpha",
                role=UserRole.HOLDER.value,
                is_active=True,
            )
            user_b = User(
                id=uuid.uuid4(),
                email=f"user_b_{uuid.uuid4().hex[:6]}@ledgerline.com",
                password_hash=hash_password("ValidPassword123!"),
                full_name="User Beta",
                role=UserRole.HOLDER.value,
                is_active=True,
            )
            admin_session.add_all([user_a, user_b])
            admin_session.flush()

            account_a = Account(
                id=uuid.uuid4(),
                account_number=f"ACC-A-{uuid.uuid4().hex[:6].upper()}",
                account_name="Account Alpha",
                balance=0,
                currency="INR",
                status=AccountStatus.ACTIVE.value,
            )
            account_b = Account(
                id=uuid.uuid4(),
                account_number=f"ACC-B-{uuid.uuid4().hex[:6].upper()}",
                account_name="Account Beta",
                balance=0,
                currency="INR",
                status=AccountStatus.ACTIVE.value,
            )
            admin_session.add_all([account_a, account_b])
            admin_session.flush()

            mem_a = AccountMembership(
                id=uuid.uuid4(),
                account_id=account_a.id,
                user_id=user_a.id,
                membership_role=MembershipRole.OWNER.value,
            )
            mem_b = AccountMembership(
                id=uuid.uuid4(),
                account_id=account_b.id,
                user_id=user_b.id,
                membership_role=MembershipRole.OWNER.value,
            )
            admin_session.add_all([mem_a, mem_b])
            admin_session.commit()

            created_user_ids.extend([user_a.id, user_b.id])
            created_account_ids.extend([account_a.id, account_b.id])
            acc_a_id = account_a.id
            acc_b_id = account_b.id
        finally:
            admin_session.close()

        # Step 1: Execute Deposit (₹1000 = 100000 paise) using app session
        user_a_app = session.get(User, created_user_ids[0])
        dep_resp = execute_deposit(
            db=session,
            user=user_a_app,
            account_id=acc_a_id,
            amount_paise=100000,
            idempotency_key=str(uuid.uuid4()),
        )
        assert dep_resp["status"] == "POSTED"

        # Step 2: Execute Transfer (₹400 = 40000 paise) from A to B using app session
        trf_resp = execute_transfer(
            db=session,
            user=user_a_app,
            source_account_id=acc_a_id,
            destination_account_id=acc_b_id,
            amount_paise=40000,
            idempotency_key=str(uuid.uuid4()),
        )
        assert trf_resp["status"] == "POSTED"

        # Step 3: Execute Withdrawal (₹200 = 20000 paise) from A using app session
        wth_resp = execute_withdrawal(
            db=session,
            user=user_a_app,
            account_id=acc_a_id,
            amount_paise=20000,
            idempotency_key=str(uuid.uuid4()),
        )
        assert wth_resp["status"] == "POSTED"

        # Verify balances
        acc_a_refreshed = session.get(Account, acc_a_id)
        acc_b_refreshed = session.get(Account, acc_b_id)
        assert acc_a_refreshed.balance == 40000  # 100000 - 40000 - 20000 = 40000
        assert acc_b_refreshed.balance == 40000

    finally:
        session.close()
        _cleanup_test_records(test_engine, created_user_ids, created_account_ids)


def test_11_ledger_reconciliation_remains_correct(test_engine: Engine, app_test_engine: Engine):
    """11. Verify that double-entry ledger invariant sum(Credits) - sum(Debits) == balance holds perfectly."""
    session_factory = sessionmaker(bind=app_test_engine, autocommit=False, autoflush=False)
    session = session_factory()

    created_user_ids: list[uuid.UUID] = []
    created_account_ids: list[uuid.UUID] = []

    try:
        admin_session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)()
        try:
            get_or_create_system_clearing_account(admin_session)

            user = User(
                id=uuid.uuid4(),
                email=f"recon_{uuid.uuid4().hex[:6]}@ledgerline.com",
                password_hash=hash_password("ValidPassword123!"),
                full_name="Recon User",
                role=UserRole.HOLDER.value,
                is_active=True,
            )
            admin_session.add(user)
            admin_session.flush()

            account = Account(
                id=uuid.uuid4(),
                account_number=f"RECON-{uuid.uuid4().hex[:6].upper()}",
                account_name="Reconciliation Account",
                balance=0,
                currency="INR",
                status=AccountStatus.ACTIVE.value,
            )
            admin_session.add(account)
            admin_session.flush()

            mem = AccountMembership(
                id=uuid.uuid4(),
                account_id=account.id,
                user_id=user.id,
                membership_role=MembershipRole.OWNER.value,
            )
            admin_session.add(mem)
            admin_session.commit()

            created_user_ids.append(user.id)
            created_account_ids.append(account.id)
            acc_id = account.id
            usr_id = user.id
        finally:
            admin_session.close()

        # Perform deposit and withdrawal under app session
        user_app = session.get(User, usr_id)
        execute_deposit(
            db=session,
            user=user_app,
            account_id=acc_id,
            amount_paise=250000,
            idempotency_key=str(uuid.uuid4()),
        )
        execute_withdrawal(
            db=session,
            user=user_app,
            account_id=acc_id,
            amount_paise=75000,
            idempotency_key=str(uuid.uuid4()),
        )

        # Check reconciliation: sum of credits - sum of debits must match account balance exactly
        with test_engine.connect() as conn:
            credits = conn.execute(
                text("SELECT COALESCE(SUM(amount_paise), 0) FROM ledger_entries WHERE account_id = :id AND entry_type = 'CREDIT'"),
                {"id": acc_id},
            ).scalar()
            debits = conn.execute(
                text("SELECT COALESCE(SUM(amount_paise), 0) FROM ledger_entries WHERE account_id = :id AND entry_type = 'DEBIT'"),
                {"id": acc_id},
            ).scalar()
            acc_balance = conn.execute(
                text("SELECT balance FROM accounts WHERE id = :id"),
                {"id": acc_id},
            ).scalar()

            assert (credits - debits) == acc_balance == 175000

    finally:
        session.close()
        _cleanup_test_records(test_engine, created_user_ids, created_account_ids)


def test_12_test_cleanup_works_using_isolated_admin_mechanism(test_engine: Engine):
    """12. Verify that test cleanup works using the isolated admin mechanism and leaves triggers enabled."""
    session_factory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = session_factory()

    try:
        user = User(
            id=uuid.uuid4(),
            email=f"cln_{uuid.uuid4().hex[:6]}@ledgerline.com",
            password_hash=hash_password("ValidPassword123!"),
            full_name="Cleanup Test User",
            role=UserRole.HOLDER.value,
            is_active=True,
        )
        session.add(user)
        session.flush()

        account = Account(
            id=uuid.uuid4(),
            account_number=f"CLN-{uuid.uuid4().hex[:6].upper()}",
            account_name="Cleanup Account",
            balance=1000,
            currency="INR",
            status=AccountStatus.ACTIVE.value,
        )
        session.add(account)
        session.flush()

        tx = Transaction(
            id=uuid.uuid4(),
            reference=f"TX-CLN-{uuid.uuid4().hex[:6]}",
            transaction_type=TransactionType.DEPOSIT.value,
            status=TransactionStatus.POSTED.value,
            amount_paise=1000,
            currency="INR",
            description="Cleanup test deposit",
            initiated_by=user.id,
        )
        session.add(tx)
        session.flush()

        entry = LedgerEntry(
            id=uuid.uuid4(),
            account_id=account.id,
            transaction_id=tx.id,
            entry_type=EntryType.CREDIT.value,
            amount_paise=1000,
        )
        session.add(entry)
        session.commit()

        entry_id = entry.id
        user_id = user.id
        account_id = account.id
    finally:
        session.close()

    # Verify record exists
    with test_engine.connect() as conn:
        assert conn.execute(select(LedgerEntry.id).where(LedgerEntry.id == entry_id)).scalar() is not None

    # Execute isolated admin cleanup
    _cleanup_test_records(test_engine, [user_id], [account_id])

    # Verify record was deleted
    with test_engine.connect() as conn:
        assert conn.execute(select(LedgerEntry.id).where(LedgerEntry.id == entry_id)).scalar() is None

        # Verify trigger is active and enabled
        trg_status = conn.execute(
            text("SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_ledger_entries_immutability'")
        ).scalar()
        # 'O' in PostgreSQL means origin/enabled
        assert trg_status == "O"


def test_13_application_engine_connects_as_runtime_role(app_test_engine: Engine):
    """13. Verify that the runtime application engine connects as unprivileged role ledgerline_app."""
    with app_test_engine.connect() as conn:
        current_user = conn.execute(text("SELECT current_user;")).scalar()
        assert current_user == "ledgerline_app"
        db_name = conn.execute(text("SELECT current_database();")).scalar()
        assert db_name == "ledgerline_test"


def test_14_migration_role_is_not_superuser(test_engine: Engine):
    """14. Verify that the migration role ledgerline_migrator is NOT a superuser and lacks dangerous privileges."""
    with test_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = 'ledgerline_migrator';"
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "ledgerline_migrator"
        assert row[1] is False  # rolsuper
        assert row[2] is False  # rolcreatedb
        assert row[3] is False  # rolcreaterole
        assert row[4] is False  # rolreplication
        assert row[5] is False  # rolbypassrls


def test_15_migration_role_owns_schema_and_tables(test_engine: Engine):
    """15. Verify that the migration role ledgerline_migrator owns the public schema and domain tables."""
    with test_engine.connect() as conn:
        # Public schema owner
        schema_owner = conn.execute(
            text("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'public';")
        ).scalar()
        assert schema_owner == "ledgerline_migrator"

        # Domain table owners
        tables = [
            "accounts",
            "account_memberships",
            "users",
            "sessions",
            "transactions",
            "ledger_entries",
            "idempotency_records",
            "audit_events",
            "alembic_version",
        ]
        for table in tables:
            owner = conn.execute(
                text("SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = :t;"),
                {"t": table},
            ).scalar()
            assert owner == "ledgerline_migrator"

        # Immutability functions owner
        for func in ["protect_ledger_entries_immutability", "protect_ledger_entries_truncate"]:
            func_owner = conn.execute(
                text(
                    "SELECT pg_get_userbyid(proowner) FROM pg_proc JOIN pg_namespace n ON pg_proc.pronamespace = n.oid "
                    "WHERE n.nspname = 'public' AND proname = :f;"
                ),
                {"f": func},
            ).scalar()
            assert func_owner == "ledgerline_migrator"


def test_16_migration_role_cannot_perform_superuser_actions(test_engine: Engine):
    """16. Verify that the migration role cannot alter roles to superuser or create databases."""
    with test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("ALTER ROLE ledgerline_migrator SUPERUSER;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"

    with test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("CREATE ROLE some_unauthorized_role;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_17_runtime_role_cannot_become_member_of_migration_or_admin_role(app_test_engine: Engine):
    """17. Verify that the runtime role ledgerline_app cannot grant itself membership in migration or admin roles."""
    # Cannot become member of ledgerline_migrator
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("GRANT ledgerline_migrator TO ledgerline_app;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"

    # Cannot become member of bootstrap admin ledgerline
    with app_test_engine.connect() as conn:
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("GRANT ledgerline TO ledgerline_app;"))
        err = exc_info.value
        assert getattr(err.orig, "pgcode", None) == "42501"


def test_18_default_privileges_apply_to_newly_created_objects(test_engine: Engine, app_test_engine: Engine):
    """18. Verify that default privileges configured for ledgerline_migrator grant DML access to ledgerline_app."""
    # 1. Migration role creates a new table and sequence in public schema
    with test_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS probe_table_default_priv;"))
        conn.execute(text("CREATE TABLE probe_table_default_priv (id serial primary key, note text);"))

    try:
        # 2. Runtime application role connects and exercises SELECT, INSERT, UPDATE, DELETE via default privileges
        with app_test_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO probe_table_default_priv (note) VALUES (:val);"),
                {"val": "created_by_app"},
            )
            rows = conn.execute(text("SELECT note FROM probe_table_default_priv;")).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "created_by_app"

            conn.execute(
                text("UPDATE probe_table_default_priv SET note = :val WHERE note = 'created_by_app';"),
                {"val": "updated_by_app"},
            )
            updated = conn.execute(text("SELECT note FROM probe_table_default_priv;")).scalar()
            assert updated == "updated_by_app"

            conn.execute(text("DELETE FROM probe_table_default_priv;"))
            count = conn.execute(text("SELECT count(*) FROM probe_table_default_priv;")).scalar()
            assert count == 0
    finally:
        # 3. Clean up probe table using migration owner connection
        with test_engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS probe_table_default_priv;"))


def test_19_audit_events_immutability_under_runtime_role(test_engine: Engine, app_test_engine: Engine):
    """Verify that runtime role (ledgerline_app) can INSERT into audit_events but cannot UPDATE, DELETE, or TRUNCATE.

    PostgreSQL grants:
    - REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM ledgerline_app;
    - GRANT SELECT, INSERT ON audit_events TO ledgerline_app;
    """
    test_event_id = uuid.uuid4()

    # 1. Runtime application role successfully inserts an audit event
    with app_test_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_events (id, action, entity_type, entity_id, metadata, created_at) "
                "VALUES (:id, 'TEST_AUDIT', 'Test', :ent_id, '{\"key\": \"val\"}'::jsonb, clock_timestamp());"
            ),
            {"id": str(test_event_id), "ent_id": str(uuid.uuid4())},
        )
        row = conn.execute(
            text("SELECT action FROM audit_events WHERE id = :id;"),
            {"id": str(test_event_id)},
        ).scalar()
        assert row == "TEST_AUDIT"

    # 2. Runtime application role attempts direct SQL UPDATE -> rejected with 42501 (permission denied)
    with pytest.raises(DBAPIError) as exc_update:
        with app_test_engine.begin() as conn:
            conn.execute(
                text("UPDATE audit_events SET action = 'HACKED' WHERE id = :id;"),
                {"id": str(test_event_id)},
            )
    assert getattr(exc_update.value.orig, "pgcode", None) == "42501" or "permission denied" in str(exc_update.value).lower()

    # 3. Runtime application role attempts direct SQL DELETE -> rejected with 42501 (permission denied)
    with pytest.raises(DBAPIError) as exc_delete:
        with app_test_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM audit_events WHERE id = :id;"),
                {"id": str(test_event_id)},
            )
    assert getattr(exc_delete.value.orig, "pgcode", None) == "42501" or "permission denied" in str(exc_delete.value).lower()

    # 4. Runtime application role attempts TRUNCATE -> rejected with 42501 (permission denied)
    with pytest.raises(DBAPIError) as exc_trunc:
        with app_test_engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE audit_events;"))
    assert getattr(exc_trunc.value.orig, "pgcode", None) == "42501" or "permission denied" in str(exc_trunc.value).lower()

    # 5. Clean up the inserted audit event using the migration owner connection (ledgerline_migrator)
    with test_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM audit_events WHERE id = :id;"),
            {"id": str(test_event_id)},
        )

