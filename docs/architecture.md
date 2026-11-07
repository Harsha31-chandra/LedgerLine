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
   Account balance snapshots (`accounts.balance`) are operational performance caches. They **never** replace the append-only ledger (`ledger_entries`) as the financial source of truth.
2. **Integer Paise Representation**:
   All monetary calculations and storage use 64-bit integer minor units (paise via `BigInteger`). Floating-point arithmetic is strictly forbidden.
3. **Double-Entry Balance**:
   Every financial transaction consists of balanced debits and credits ($\sum \text{Debits} == \sum \text{Credits}$).
4. **No Unbounded Overdraw**:
   Account balances must not drop below zero (`balance >= 0` check constraint enforced on `accounts`).
5. **Exactly-Once Execution**:
   Replaying a request with the same `(user_id, idempotency_key)` returns the identical original result without moving money again.

## Database Schema & Initial Migration State

The foundational relational schema is defined by eight SQLAlchemy 2.x declarative models and compiled via Alembic into baseline migration `7717a26bd3d3_initial_schema` ([`backend/migrations/versions/7717a26bd3d3_initial_schema.py`](../backend/migrations/versions/7717a26bd3d3_initial_schema.py)).

### Verified Migration Status
- **Target Database:** Verified and applied exclusively to the isolated test database `ledgerline_test` (`localhost:5432`).
- **Command:** `python -m alembic -c backend\alembic.ini upgrade head` (Result: `Running upgrade  -> 7717a26bd3d3, initial schema`).
- **Table Verification:** `ledgerline_test` contains all eight application domain tables plus `alembic_version` (storing revision `7717a26bd3d3`).
- **Schema Drift Check:** Verified clean via `python -m alembic -c backend\alembic.ini check` (`No new upgrade operations detected`).
- **Environment Isolation:** The initial migration was applied to `ledgerline_test`. The development database (`ledgerline`) was not targeted by that migration, and its complete contents have not been independently verified. Application business logic (authentication, authorization, transfer processing, and ledger posting) is scheduled for subsequent phases.

### Domain Tables Overview
1. **`users`**: Authenticated principals with system roles (`ADMIN`, `HOLDER`, `AUDITOR`), unique indexed email, and password hash.
2. **`sessions`**: Server-managed, revocable login sessions with unique indexed `token_hash`, expiry, and activity tracking.
3. **`accounts`**: Financial accounts with integer paise balance cache, unique indexed account number, and status (`ACTIVE`, `FROZEN`, `CLOSED`).
4. **`account_memberships`**: User-to-account entitlements (`OWNER`, `OPERATOR`, `VIEWER`) with compound unique constraint `(user_id, account_id)` preventing BOLA/IDOR vulnerabilities.
5. **`transactions`**: Business intent headers tracking reference, operation type (`DEPOSIT`, `WITHDRAWAL`, `TRANSFER`), and lifecycle status (`PENDING`, `POSTED`, `REJECTED`).
6. **`ledger_entries`**: Double-entry financial journal lines (`DEBIT`, `CREDIT`, positive `amount_paise`). Foreign keys to `accounts` and `transactions` specify `ondelete='RESTRICT'`, which protects referenced parent records from deletion while ledger entries reference them (note: database-enforced immutability preventing direct `UPDATE` or `DELETE` on ledger entries themselves is not yet implemented).
7. **`idempotency_records`**: Exactly-once execution records with compound unique constraint `(user_id, idempotency_key)`, canonical request hash, and cached response payload.
8. **`audit_events`**: Append-only security and operational audit trail with composite action/time index and `SET NULL` on actor user reference.

## Remaining Engineering Considerations (Implementation Roadmap)

The following architectural and security capabilities are distinguished from the initial schema migration and represent scheduled Day 2 / Day 3 engineering tasks:

1. **Atomic Double-Entry Ledger Posting & Invariant Validation:**
   Atomic debit/credit generation, running balance computation, and verification of $\sum \text{Debits} == \sum \text{Credits}$ within single PostgreSQL transactions in `ledger_service.py`.
2. **Database-Enforced Immutability for Posted Ledger Entries:**
   Database-enforced append-only behavior is not implemented yet. While `ON DELETE RESTRICT` protects referenced parent accounts and transactions from deletion, it does not prevent direct `UPDATE` or `DELETE` operations on ledger entries themselves. Enforcing true append-only behavior at the database layer (via PostgreSQL role permission revocation or a `BEFORE UPDATE OR DELETE` trigger) remains a future engineering requirement.
3. **Database Trigger for Automatic `updated_at` Refresh:**
   Server-side PostgreSQL trigger (`BEFORE UPDATE ... NEW.updated_at = clock_timestamp()`) to guarantee timestamp refresh on raw SQL updates outside the SQLAlchemy ORM unit-of-work.
4. **PostgreSQL Row-Level Security (RLS):**
   Engine-level RLS policies if required by the eventual multi-tenant threat model beyond application-level authorization in `AccountMembership` and `authorization_service.py`.

---
*For a complete chronological log of all AI-assisted tasks, prompt texts, and audit results, see [`PROMPTS.md`](../PROMPTS.md).*
