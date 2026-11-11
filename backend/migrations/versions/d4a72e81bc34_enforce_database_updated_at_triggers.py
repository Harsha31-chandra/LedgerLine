"""enforce database-level updated_at triggers on mutable tables

Revision ID: d4a72e81bc34
Revises: c18f3a8b9e10
Create Date: 2026-11-09 14:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4a72e81bc34"
down_revision: Union[str, None] = "c18f3a8b9e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite unit test environments do not support PL/pgSQL
        return

    # 1. Create or replace reusable PL/pgSQL trigger function
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Preserve immutability of created_at on UPDATE
            NEW.created_at = OLD.created_at;

            -- Avoid unnecessary timestamp refresh on no-op updates
            IF (NEW IS NOT DISTINCT FROM OLD) THEN
                RETURN OLD;
            END IF;

            -- Refresh updated_at using timezone-aware wall-clock time
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 2. Attach triggers to mutable tables possessing an updated_at column
    # Table: accounts
    op.execute("DROP TRIGGER IF EXISTS trg_accounts_updated_at ON accounts;")
    op.execute(
        """
        CREATE TRIGGER trg_accounts_updated_at
        BEFORE UPDATE ON accounts
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
        """
    )

    # Table: users
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users;")
    op.execute(
        """
        CREATE TRIGGER trg_users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
        """
    )

    # Table: transactions
    op.execute("DROP TRIGGER IF EXISTS trg_transactions_updated_at ON transactions;")
    op.execute(
        """
        CREATE TRIGGER trg_transactions_updated_at
        BEFORE UPDATE ON transactions
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # 1. Drop triggers
    op.execute("DROP TRIGGER IF EXISTS trg_transactions_updated_at ON transactions;")
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users;")
    op.execute("DROP TRIGGER IF EXISTS trg_accounts_updated_at ON accounts;")

    # 2. Drop function
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")
