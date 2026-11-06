"""
Ledger service.

Core double-entry financial posting engine.
Generates balanced debit and credit entries, verifies sum(debits) == sum(credits),
and enforces append-only semantics.
"""
