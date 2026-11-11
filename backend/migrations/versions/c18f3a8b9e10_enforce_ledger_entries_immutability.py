"""enforce ledger entries immutability and role separation

Revision ID: c18f3a8b9e10
Revises: 27022f5fc965
Create Date: 2026-11-09 13:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c18f3a8b9e10"
down_revision: Union[str, None] = "27022f5fc965"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite unit test environments do not support PL/pgSQL or PostgreSQL roles
        return

    # 1. Create or replace trigger function for row-level immutability enforcement
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_ledger_entries_immutability()
        RETURNS TRIGGER AS $$
        BEGIN
            IF (TG_OP = 'UPDATE') THEN
                RAISE EXCEPTION 'Financial ledger entries are strictly immutable: UPDATE is prohibited on ledger_entries (id=%)', OLD.id
                    USING ERRCODE = '20000',
                          HINT = 'LedgerLine enforces an append-only ledger. Financial adjustments must be recorded as new compensating transactions and ledger entries.';
            ELSIF (TG_OP = 'DELETE') THEN
                RAISE EXCEPTION 'Financial ledger entries are strictly immutable: DELETE is prohibited on ledger_entries (id=%)', OLD.id
                    USING ERRCODE = '20000',
                          HINT = 'LedgerLine enforces an append-only ledger. Historical financial entries cannot be deleted.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 2. Attach row-level BEFORE UPDATE OR DELETE trigger to ledger_entries
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ledger_entries_immutability ON ledger_entries;"
    )
    op.execute(
        """
        CREATE TRIGGER trg_ledger_entries_immutability
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW
        EXECUTE FUNCTION protect_ledger_entries_immutability();
        """
    )

    # 3. Create or replace trigger function for statement-level truncate protection
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_ledger_entries_truncate()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Financial ledger entries are strictly immutable: TRUNCATE is prohibited on ledger_entries'
                USING ERRCODE = '20000',
                      HINT = 'LedgerLine enforces an append-only ledger. Truncating financial records is strictly forbidden.';
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 4. Attach statement-level BEFORE TRUNCATE trigger to ledger_entries
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ledger_entries_truncate ON ledger_entries;"
    )
    op.execute(
        """
        CREATE TRIGGER trg_ledger_entries_truncate
        BEFORE TRUNCATE ON ledger_entries
        FOR EACH STATEMENT
        EXECUTE FUNCTION protect_ledger_entries_truncate();
        """
    )

    # 5. Create dedicated runtime application role if it does not already exist
    # Enforces principle of least privilege: NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ledgerline_app') THEN
                IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = current_user AND (rolsuper OR rolcreaterole)) THEN
                    CREATE ROLE ledgerline_app WITH LOGIN PASSWORD 'ledgerline_app_dev'
                        NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
                END IF;
            END IF;
        END
        $$;
        """
    )

    # 6. Grant schema usage and granular least-privilege permissions to ledgerline_app
    op.execute("GRANT USAGE ON SCHEMA public TO ledgerline_app;")

    # Standard transactional tables: SELECT, INSERT, UPDATE, DELETE (where domain requirements permit)
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            accounts,
            account_memberships,
            users,
            sessions,
            transactions,
            idempotency_records
        TO ledgerline_app;
        """
    )

    # Append-only audit events table: strictly SELECT, INSERT only (NO UPDATE, NO DELETE, NO TRUNCATE)
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM ledgerline_app;")
    op.execute("GRANT SELECT, INSERT ON audit_events TO ledgerline_app;")

    # Financial ledger entries table: strictly SELECT, INSERT only (NO UPDATE, NO DELETE, NO TRUNCATE)
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON ledger_entries FROM ledgerline_app;")
    op.execute("GRANT SELECT, INSERT ON ledger_entries TO ledgerline_app;")

    # Sequences in public schema (if any)
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledgerline_app;"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # 1. Drop triggers
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ledger_entries_truncate ON ledger_entries;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ledger_entries_immutability ON ledger_entries;"
    )

    # 2. Drop trigger functions
    op.execute("DROP FUNCTION IF EXISTS protect_ledger_entries_truncate();")
    op.execute(
        "DROP FUNCTION IF EXISTS protect_ledger_entries_immutability();"
    )

    # 3. Revoke permissions from ledgerline_app if role exists
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ledgerline_app') THEN
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM ledgerline_app;
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM ledgerline_app;
                REVOKE USAGE ON SCHEMA public FROM ledgerline_app;
            END IF;
        END
        $$;
        """
    )
