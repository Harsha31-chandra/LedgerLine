"""allow clearing debit balance

Revision ID: 27022f5fc965
Revises: 7717a26bd3d3
Create Date: 2026-11-08 14:09:40.286377
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27022f5fc965'
down_revision: Union[str, None] = '7717a26bd3d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update any existing clearing account balance snapshot to match its ledger sum
    op.execute(
        """
        UPDATE accounts
        SET balance = COALESCE(
            (SELECT SUM(CASE WHEN entry_type = 'CREDIT' THEN amount_paise ELSE -amount_paise END)
             FROM ledger_entries
             WHERE ledger_entries.account_id = accounts.id),
            0
        )
        WHERE account_number = 'SYSTEM_CLEARING'
        """
    )

    # 2. Drop existing non-negative balance constraint
    op.execute("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS ck_accounts_ck_accounts_balance_non_negative")

    # 3. Add updated constraint permitting SYSTEM_CLEARING to hold natural debit settlement balance
    op.execute(
        "ALTER TABLE accounts ADD CONSTRAINT ck_accounts_ck_accounts_balance_non_negative "
        "CHECK (balance >= 0 OR account_number = 'SYSTEM_CLEARING')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS ck_accounts_ck_accounts_balance_non_negative")
    op.execute(
        "ALTER TABLE accounts ADD CONSTRAINT ck_accounts_ck_accounts_balance_non_negative "
        "CHECK (balance >= 0)"
    )
