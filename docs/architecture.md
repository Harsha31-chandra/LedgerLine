# Architecture Notes — LedgerLine

## System Architecture

Modular monolith with clean boundary separation:
- **API Routes (`backend/app/api/`)**: Thin HTTP endpoints. Validate incoming schemas, verify authentication context, and delegate to services. Contain zero financial calculation or persistence logic.
- **Authorization Service (`backend/app/services/authorization_service.py`)**: Enforces roles (Admin, Account Holder, Auditor) and per-account entitlements (`account_memberships`). Guards against Broken Object Level Authorization (BOLA/IDOR).
- **Transaction Service (`backend/app/services/transaction_service.py`)**: Coordinates atomic database transactions with deterministic account row locks (`SELECT FOR UPDATE`), manages idempotency reservations, and coordinates rollback.
- **Ledger Service (`backend/app/services/ledger_service.py`)**: Pure double-entry financial posting engine. Generates balanced debit/credit entries, calculates running balances, and verifies $\sum \text{Debits} == \sum \text{Credits}$.
- **Reconciliation Service (`backend/app/services/reconciliation_service.py`)**: Independent auditor. Reconciles cached balance snapshots against the authoritative ledger.

## Non-Negotiable Invariants

1. **The Ledger is the Sole Source of Truth**:
   Account balance snapshots (`accounts.balance_minor`) are operational caches. They **never** replace the append-only ledger (`ledger_entries`) as the source of truth.
2. **Integer Paise Representation**:
   All monetary calculations and storage use integer minor units (paise). Floating-point arithmetic is strictly forbidden.
3. **Double-Entry Balance**:
   Every financial transaction consists of balanced debits and credits ($\sum \text{Debits} == \sum \text{Credits}$).
4. **No Unbounded Overdraw**:
   Account balances must not drop below zero (unless an explicit, authorized overdraft limit is configured and enforced).
5. **Exactly-Once Execution**:
   Replaying a request with the same `(actor_user_id, idempotency_key)` returns the identical original result without moving money again.
