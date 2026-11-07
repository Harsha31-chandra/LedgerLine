"""
Unit tests verifying SQLAlchemy 2.x model metadata, constraints, and relationships.
"""

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
import sqlalchemy.types as types

from backend.app.models.account import Account, AccountStatus
from backend.app.models.account_membership import AccountMembership, MembershipRole
from backend.app.models.audit_event import AuditEvent
from backend.app.models.base import Base
from backend.app.models.idempotency import IdempotencyRecord
from backend.app.models.ledger_entry import EntryType, LedgerEntry
from backend.app.models.session import Session
from backend.app.models.transaction import Transaction, TransactionStatus, TransactionType
from backend.app.models.user import User, UserRole


def test_eight_models_registered_in_metadata():
    """Verify that exactly eight tables are registered in Base.metadata."""
    expected_tables = {
        "users",
        "sessions",
        "accounts",
        "account_memberships",
        "transactions",
        "ledger_entries",
        "idempotency_records",
        "audit_events",
    }
    registered_tables = set(Base.metadata.tables.keys())
    assert registered_tables == expected_tables
    assert len(registered_tables) == 8


def test_all_eight_model_classes_exported_in_models_package():
    """Verify that all eight model classes are exported in backend.app.models and mapped."""
    import backend.app.models as models

    expected_classes = [
        models.User,
        models.Session,
        models.Account,
        models.AccountMembership,
        models.Transaction,
        models.LedgerEntry,
        models.IdempotencyRecord,
        models.AuditEvent,
    ]
    for cls in expected_classes:
        assert hasattr(cls, "__tablename__")
        assert cls.__tablename__ in Base.metadata.tables


def test_primary_keys_exist_on_all_tables():
    """Verify that every table defines a primary key constraint."""
    for table_name, table in Base.metadata.tables.items():
        pk_cols = list(table.primary_key.columns)
        assert len(pk_cols) >= 1, f"Table {table_name} lacks a primary key"
        assert pk_cols[0].name == "id", f"Table {table_name} primary key is not 'id'"


def test_foreign_keys_defined_correctly():
    """Verify foreign key target definitions across dependent tables."""
    fk_expectations = {
        "sessions": [("user_id", "users.id")],
        "account_memberships": [("user_id", "users.id"), ("account_id", "accounts.id")],
        "transactions": [("initiated_by", "users.id")],
        "ledger_entries": [("transaction_id", "transactions.id"), ("account_id", "accounts.id")],
        "idempotency_records": [("user_id", "users.id")],
        "audit_events": [("actor_user_id", "users.id")],
    }

    for table_name, expected_fks in fk_expectations.items():
        table = Base.metadata.tables[table_name]
        actual_fks = [(fk.parent.name, fk.target_fullname) for fk in table.foreign_keys]
        for parent_col, target in expected_fks:
            assert (parent_col, target) in actual_fks, (
                f"Missing FK {parent_col} -> {target} on table {table_name}"
            )


def test_unique_constraints_and_indexes():
    """Verify unique indexes and compound unique constraints."""
    # users.email must be unique
    users_table = Base.metadata.tables["users"]
    assert users_table.c.email.unique or any(
        isinstance(c, UniqueConstraint) and "email" in [col.name for col in c.columns]
        for c in users_table.constraints
    )

    # accounts.account_number must be unique
    accounts_table = Base.metadata.tables["accounts"]
    assert accounts_table.c.account_number.unique or any(
        isinstance(c, UniqueConstraint) and "account_number" in [col.name for col in c.columns]
        for c in accounts_table.constraints
    )

    # sessions.token_hash must be unique
    sessions_table = Base.metadata.tables["sessions"]
    assert sessions_table.c.token_hash.unique or any(
        isinstance(c, UniqueConstraint) and "token_hash" in [col.name for col in c.columns]
        for c in sessions_table.constraints
    )

    # transactions.reference must be unique
    tx_table = Base.metadata.tables["transactions"]
    assert tx_table.c.reference.unique or any(
        isinstance(c, UniqueConstraint) and "reference" in [col.name for col in c.columns]
        for c in tx_table.constraints
    )

    # account_memberships(user_id, account_id) unique constraint
    memberships_table = Base.metadata.tables["account_memberships"]
    membership_uq = [
        [col.name for col in c.columns]
        for c in memberships_table.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert ["user_id", "account_id"] in membership_uq

    # idempotency_records(user_id, idempotency_key) unique constraint
    idemp_table = Base.metadata.tables["idempotency_records"]
    idemp_uq = [
        [col.name for col in c.columns]
        for c in idemp_table.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert ["user_id", "idempotency_key"] in idemp_uq


def test_monetary_columns_use_biginteger_not_float():
    """Verify that monetary values are strictly represented as BigInteger paise, never float."""
    accounts_table = Base.metadata.tables["accounts"]
    tx_table = Base.metadata.tables["transactions"]
    ledger_table = Base.metadata.tables["ledger_entries"]

    assert isinstance(accounts_table.c.balance.type, BigInteger)
    assert isinstance(tx_table.c.amount_paise.type, BigInteger)
    assert isinstance(ledger_table.c.amount_paise.type, BigInteger)

    # Ensure no float types exist in any table
    for table_name, table in Base.metadata.tables.items():
        for column in table.columns:
            assert not isinstance(column.type, (types.Float, types.REAL)), (
                f"Floating-point column detected: {table_name}.{column.name}"
            )


def test_database_check_constraints():
    """Verify check constraints for positive amounts, non-negative balances, and valid enums."""
    accounts_table = Base.metadata.tables["accounts"]
    tx_table = Base.metadata.tables["transactions"]
    ledger_table = Base.metadata.tables["ledger_entries"]
    users_table = Base.metadata.tables["users"]

    def get_check_clauses(table):
        return [str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)]

    # accounts: balance >= 0
    assert any("balance >= 0" in clause for clause in get_check_clauses(accounts_table))

    # transactions: amount_paise > 0
    assert any("amount_paise > 0" in clause for clause in get_check_clauses(tx_table))

    # ledger_entries: amount_paise > 0
    assert any("amount_paise > 0" in clause for clause in get_check_clauses(ledger_table))

    # users: role validation
    assert any("role IN" in clause for clause in get_check_clauses(users_table))


def test_enum_definitions():
    """Verify that domain enums provide the expected values."""
    assert set(UserRole) == {"ADMIN", "HOLDER", "AUDITOR"}
    assert set(AccountStatus) == {"ACTIVE", "FROZEN", "CLOSED"}
    assert set(MembershipRole) == {"OWNER", "OPERATOR", "VIEWER"}
    assert set(TransactionType) == {"DEPOSIT", "WITHDRAWAL", "TRANSFER"}
    assert set(TransactionStatus) == {"PENDING", "POSTED", "REJECTED"}
    assert set(EntryType) == {"DEBIT", "CREDIT"}
