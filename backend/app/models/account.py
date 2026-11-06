"""
Account model — represents customer wallets and system clearing accounts.

CRITICAL FINANCIAL INVARIANT:
The `balance_minor` column on this table is an operational performance cache (snapshot).
It MUST NEVER replace the authoritative ledger (`ledger_entries`) as the source of truth.
The true, auditable balance of any account is always derived from the sum of its
immutable, signed ledger postings (opening balance + sum of signed postings).
A background/on-demand reconciliation service verifies that balance_minor equals
the sum of ledger entries.
"""
