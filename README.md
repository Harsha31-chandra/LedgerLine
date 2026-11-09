# LedgerLine

**Money movement with a ledger you can prove.**

> A simulated financial transaction system built for the Snovasys Fresher Hiring Challenge 2026 (VVIT). This is an assessment project using simulated money — it is not a real bank or payment service.

## Overview

LedgerLine moves money between accounts while proving that money is never created, lost or moved twice. Every operation is processed in one PostgreSQL transaction with row-level locks, balanced double-entry ledger postings, idempotency protection, and a complete audit trail.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + FastAPI + Argon2id |
| Database | PostgreSQL 16 (via Docker) |
| ORM / Migrations | SQLAlchemy 2.x + Alembic |
| Frontend | React 19 + TypeScript + Vite 8 + Vitest |
| Tests | Pytest + HTTPX |

## Quick Start

```powershell
# 1. Clone
git clone <YOUR_REPOSITORY_URL>
cd LedgerLine

# 2. Start PostgreSQL
docker compose up -d

# 3. Backend setup
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt

# 4. Configure environment
cd ..
copy .env.example .env
# Ensure MIGRATION_DATABASE_URL and TEST_DATABASE_URL are configured

# 5. Run migrations (requires explicit MIGRATION_DATABASE_URL targeting ledgerline_test)
alembic -c backend/alembic.ini upgrade head

# 6. Seed demo data
python -m backend.app.scripts.seed_demo

# 7. Start API server
uvicorn backend.app.main:app --reload --port 8000

# 8. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## Demo Credentials

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@ledgerline.com | SecurePass123! |
| Account Holder | holder@ledgerline.com | SecurePass123! |
| Auditor | auditor@ledgerline.com | SecurePass123! |

> ⚠️ **Evaluation Only**: These demo credentials are strictly intended for local assessment, development, and integration testing. They must never be deployed, exposed, or enabled in production environments. Production deployments should provision initial administrators via secure out-of-band bootstrapping scripts and require mandatory immediate password rotation and multi-factor authentication.

## Role & Authorization Matrix

### Global Roles

| Capability | Admin | Account Holder | Auditor |
|-----------|-------|---------------|---------|
| Create/freeze accounts | ✅ | ❌ | ❌ |
| View administrative registry (`/admin/accounts`) | ✅ (All customer accounts) | ❌ | ❌ |
| View account details (`/accounts/{id}`) | With membership | Member accounts only | Read-only member accounts |
| Deposit/withdraw | Controlled (with membership) | Member accounts (OPERATOR/OWNER) | ❌ Never |
| Transfer | Controlled (with membership) | Member accounts (OPERATOR/OWNER) | ❌ Never |
| View audit trail | ✅ System-wide | Own events | Read-only system-wide |
| Edit/delete ledger | ❌ Never | ❌ Never | ❌ Never |

### Account Membership Roles (`account_memberships`)

| Capability | OWNER | OPERATOR | VIEWER |
|-----------|-------|----------|--------|
| View account balance & transactions | ✅ | ✅ | ✅ |
| Initiate operations (deposit, withdraw, transfer) | ✅ | ✅ | ❌ (403 Forbidden) |
| Manage account memberships (add/remove) | ✅ | ❌ (403 Forbidden) | ❌ (403 Forbidden) |
| Update account details | ✅ | ❌ (403 Forbidden) | ❌ (403 Forbidden) |

> 🔒 **Conflict Resolution Invariant:** A global `AUDITOR` remains strictly read-only even if assigned `OWNER` or `OPERATOR` membership. Non-members querying an account UUID receive HTTP 404 (Anti-IDOR). Operational actions on `FROZEN` or `CLOSED` accounts are rejected with HTTP 403.


## Money Invariants

1. Every posted transaction balances: total debit = total credit.
2. No customer wallet balance falls below zero (`balance >= 0` check constraint enforced on customer accounts).
3. System clearing account (`SYSTEM_CLEARING`) starts at 0 balance, reflects external rail claims/obligations (permitting debit balances via `ck_accounts_balance_non_negative`), and reconciles exactly with its ledger entries.
4. Internal transfers leave the sum of customer wallets unchanged ($\sum \text{Customer Balances} + \text{Clearing Balance} == 0$).
5. One idempotency key maps to at most one financial effect.
6. Balance snapshots equal the balance derived from posted ledger entries (`reconcile_account_balance` returns `is_reconciled=True`).

## Database Environment Isolation

LedgerLine strictly isolates development, testing, and migration database environments:

- **`DATABASE_URL`**: Used exclusively for application development runtime (`ledgerline`). Never used for tests or migration commands.
- **`TEST_DATABASE_URL`**: Used exclusively by Pytest for automated test execution (`ledgerline_test` on `localhost:5432`). Programmatically rejects connections targeting `ledgerline`.
- **`MIGRATION_DATABASE_URL`**: Required explicitly for all Alembic commands. Never falls back to `DATABASE_URL` or application settings. During initial development, migrations must target `ledgerline_test` on `localhost:5432`. No migration command can silently execute against the development database.

## Database Schema & Migration Status

- **Baseline Migration:** `7717a26bd3d3_initial_schema` ([`backend/migrations/versions/7717a26bd3d3_initial_schema.py`](backend/migrations/versions/7717a26bd3d3_initial_schema.py)).
- **Clearing Debit Balance Migration:** `27022f5fc965_allow_clearing_debit_balance` ([`backend/migrations/versions/27022f5fc965_allow_clearing_debit_balance.py`](backend/migrations/versions/27022f5fc965_allow_clearing_debit_balance.py)). Resets `SYSTEM_CLEARING` balance snapshot to 0 and updates `ck_accounts_balance_non_negative` check constraint to `CHECK (balance >= 0 OR account_number = 'SYSTEM_CLEARING')`.
- **Target Database:** Verified and applied exclusively to the isolated test database `ledgerline_test`.
- **Schema Contents:** 8 application domain tables (`users`, `sessions`, `accounts`, `account_memberships`, `transactions`, `ledger_entries`, `idempotency_records`, `audit_events`), 58 columns, 8 foreign keys (`ondelete` safeguards: `RESTRICT` on `ledger_entries` protects referenced parent accounts/transactions from deletion, `SET NULL` on audit/transaction initiators, `CASCADE` on memberships/sessions/idempotency), 9 check constraints, 2 composite unique constraints, 18 indexes, and `alembic_version`.
- **Schema Drift Check:** Verified clean via `python -m alembic -c backend\alembic.ini check` (`No new upgrade operations detected`).
- **Development Database Status:** Migrations were applied exclusively to `ledgerline_test`. The development database (`ledgerline`) was not targeted by migrations.
- **Implementation Status:** Authentication schemas, user registration, credential verification (with dummy Argon2id timing protection), secure session lifecycle, HTTP authentication endpoints (`/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me`), secure `HttpOnly`/`SameSite=Lax` session cookies, origin-based CSRF defense, rate limiting via `slowapi`, role-based access control (RBAC), account management endpoints (`/accounts`), financial transactions (`/transactions`), double-entry ledger posting, integer paise invariants, idempotency replay caching with UTC expiration, savepoint-isolated concurrency protection, and row-level pessimistic locking (`SELECT FOR UPDATE`) are fully implemented and verified.

## Authentication & HTTP Security

LedgerLine implements a defense-in-depth HTTP authentication and session management layer:

- **Endpoints (`backend/app/api/auth.py`):**
  - `POST /auth/register`: Public user registration with normalized email, server-enforced `UserRole.HOLDER`, duplicate-email detection, and generic error handling. Rate-limited to 5/minute.
  - `POST /auth/login`: Credential verification against Argon2id password hashes (with dummy hash verification to mitigate timing-based user enumeration). Sets a secure, HTTP-only session cookie and returns a safe `UserResponse`. Rate-limited to 10/minute.
  - `POST /auth/logout`: Revokes active session in the database (`revoked_at` timestamp) and deletes the session cookie with matching attributes. Predictable and idempotent.
  - `GET /auth/me`: Validates session cookie via FastAPI dependency (`get_current_user`), returning the authenticated `UserResponse`. Rejects missing, invalid, expired, revoked, or inactive sessions with HTTP 401.
- **Session Cookie Security (`backend/app/config.py`):**
  - Stored in browser cookie `ledgerline_session` with `HttpOnly=True` (inaccessible to client JavaScript), `SameSite=Lax` (safeguard against cross-site request forgery while permitting safe top-level navigations), `Path=/`, and `Secure` (tied to `settings.cookie_secure`, strictly enforced in production).
  - Raw session tokens (256-bit CSPRNG) are returned exclusively via `Set-Cookie` and never exposed in response JSON or logs. The database persists only a SHA-256 digest (`token_hash`).
- **CSRF Defense (`backend/app/core/csrf.py`):**
  - Custom `CSRFProtectMiddleware` inspects all state-changing HTTP requests (`POST`, `PUT`, `PATCH`, `DELETE`).
  - Verifies request `Origin` (or fallback `Referer`) against configured `settings.cors_origins_list` and the request host.
  - Rejects cross-origin submissions, untrusted origins, and missing/empty origin headers on state-changing requests with HTTP 403 Forbidden.
- **Rate Limiting (`backend/app/core/rate_limit.py`):**
  - Integrated via `slowapi` using client remote address (`get_remote_address`).
  - Protects unauthenticated login (`10/minute`) and registration (`5/minute`) endpoints against automated brute-force and resource-exhaustion attacks.
  - Returns generic HTTP 429 (`Too many requests. Please try again later.`) without disclosing credential details.

## Role-Based Access Control & Account Authorization

Implemented across `backend/app/services/authorization_service.py` and `backend/app/api/deps.py`:

- **Role Matrix:**
  - **Global Roles (`users.role`):** `ADMIN` (system administrator), `HOLDER` (account holder/customer), `AUDITOR` (system-wide read-only auditor).
  - **Account Membership Roles (`account_memberships.membership_role`):** `OWNER` (full account control, member management), `OPERATOR` (execute deposits, withdrawals, transfers), `VIEWER` (read-only balance, statements, ledger entries).
- **Enforcement Rules:**
  - Global `AUDITOR` read-only invariant strictly overrides any account membership role to prevent privilege escalation.
  - Anti-IDOR / Anti-BOLA policy: Unauthorized account queries return HTTP 404 (`Account not found`) rather than HTTP 403, preventing account existence discovery.
  - Mutating operations (`AccountAction.OPERATE`) are prohibited on `FROZEN` or `CLOSED` accounts.

## Financial Core, Double-Entry Ledger & Concurrency

Implemented across `backend/app/services/account_service.py`, `backend/app/services/transaction_service.py`, `backend/app/services/ledger_service.py`, and `backend/app/services/idempotency_service.py`:

- **Account Management (`backend/app/api/accounts.py` and `backend/app/api/admin.py`):**
  - `POST /accounts`: Admin-only account creation. Automatically assigns the initiating or specified user as `OWNER` within an atomic transaction.
  - `GET /accounts`: Lists accounts where the authenticated user holds active membership.
  - `GET /admin/accounts`: Administrative system account registry (Admin-only). Lists all non-system customer accounts across the platform for administrative oversight without granting account-level operational privileges or disclosing private ledger histories.
  - `GET /accounts/{id}`: Retrieves account details and membership role. Protected by anti-IDOR 404.
  - `PATCH /accounts/{id}`: Updates account metadata (`account_name`). Requires `OWNER` membership.
  - `POST /accounts/{id}/status`: Admin-only lifecycle status transition (`ACTIVE`, `FROZEN`, `CLOSED`). Prohibits modifying the status of `SYSTEM_CLEARING` (HTTP 403 `AccountStatusError`).
- **Financial Transactions (`backend/app/api/transactions.py`):**
  - `POST /transactions/deposit`: External deposit into customer account. Credits destination account, debits `SYSTEM_CLEARING`. Requires `OPERATOR` or `OWNER`. Strict integer paise validation (`gt=0, le=2^63-1`).
  - `POST /transactions/withdraw`: External withdrawal from customer account. Debits customer account, credits `SYSTEM_CLEARING`. Verifies sufficient balance under lock. Strict integer paise validation.
  - `POST /transactions/transfer`: Peer-to-peer transfer. Debits source customer account, credits destination customer account. Prohibits `SYSTEM_CLEARING` from being targeted or sourced (HTTP 400 `ClearingAccountTransferError`). Enforces distinct source and destination accounts.
  - `GET /transactions/{id}`: Detailed transaction retrieval with double-entry ledger lines. Requires active membership on at least one involved account (anti-IDOR 404 for non-members including `ADMIN` and `AUDITOR` without membership per PROMPT-030).
  - `GET /accounts/{id}/statement`: Chronological statement of posted ledger entries with transaction metadata.
- **Double-Entry Invariants:**
  - Every transaction generates balanced `DEBIT` and `CREDIT` entries where $\sum \text{Debits} == \sum \text{Credits}$.
  - System clearing account (`SYSTEM_CLEARING`, 0 opening balance) represents external rail claims/obligations, ensuring total money conservation across every operation: $\sum \text{Customer Balances} + \text{Clearing Balance} == 0$.
  - Customer accounts strictly enforce non-negative balances (`balance >= 0`); `SYSTEM_CLEARING` permits negative settlement balances.
  - Periodic reconciliation audits balance snapshots against posted ledger journals via `reconcile_account_balance` (`is_reconciled=True`).
- **Concurrency & Idempotency:**
  - **Pessimistic Row-Level Locking:** Accounts are locked using `SELECT ... FOR UPDATE` with `execution_options(populate_existing=True)` in deterministic sorted UUID order (`min(id1, id2)` then `max(id1, id2)`), eliminating deadlocks and lost updates across concurrent workers.
  - **Balance Re-Verification:** Account balance and status are re-checked under the exclusive row lock, preventing overdrafts in concurrent races.
  - **Concurrency-Safe Clearing Initialization:** `get_or_create_system_clearing_account` uses nested transaction savepoints (`begin_nested()`) to catch `IntegrityError` without session invalidation or outer transaction abort during concurrent worker initialization races.
  - **Idempotency Replay Cache & Row Locking:** Unique constraint `(user_id, idempotency_key)` on `idempotency_records` with SHA-256 canonical payload hashing. Identical replays return cached responses without re-executing transactions. Conflicting parameters trigger HTTP 409 `IdempotencyCollisionError`. Enforces UTC key expiration (`expires_at <= now`) with safe in-place reclaiming of expired or abandoned in-flight records. Initial lookup uses `SELECT ... FOR UPDATE` to eliminate concurrent reclamation race conditions in PostgreSQL.
  - **Audit Logging:** Every financial operation and status change records an immutable `AuditEvent` attached to the active database transaction.

## Frontend Single-Page Application (MVP)

LedgerLine features a production-grade React + TypeScript single-page application integrating directly with the FastAPI backend:

- **Technology & Tooling:** React 19, TypeScript 7, React Router 7, Vite 8, and Vitest.
- **Session & Cookie Security:** Uses HTTP-only `ledgerline_session` cookies managed strictly by the browser with `credentials: "include"`. Zero storage of session tokens or password hashes in `localStorage` or `sessionStorage`.
- **Automatic Session Restoration:** On page reload, `AuthProvider` queries `GET /auth/me` to restore the active session. If expired or unauthenticated, users are cleanly redirected to `/login` with location preservation.
- **Role-Aware UI:** Differentiates `ADMIN`, `HOLDER`, and `AUDITOR` permissions. Non-admin users are guarded against viewing administrative account creation controls; account members display their `OWNER`, `OPERATOR`, or `VIEWER` membership tier.
- **Financial Operations & Minor Unit Conversion:**
  - Forms for **Deposit**, **Withdrawal**, and **Transfer** accept monetary values in standard currency (Rupees) with sub-unit decimal support and safely convert to integer paise (`Math.round(rupees * 100)`) before transmission.
  - Generates client-side UUID idempotency keys (`crypto.randomUUID()`) for each new operation.
  - Reuses the identical idempotency key on form retries during network or validation failures to avoid duplicate processing.
  - Disables submit controls during active in-flight requests to prevent accidental double-submission.
- **Double-Entry Statement & Audit Modal:** Displays chronological account statements with credit/debit indicators, running ledger movements, and an interactive ledger audit dialog to inspect the balanced debit/credit legs of any posted transaction.

### Running the Frontend

```powershell
cd frontend

# Install dependencies
npm install

# Start development server with proxy to backend (http://localhost:5173)
npm run dev

# Run Vitest automated test suite (22 unit & component tests)
npm run test

# Run Oxlint linter
npm run lint

# Production build and TypeScript type check
npm run build
```

## Remaining Engineering Considerations

The following capabilities are deliberately distinguished from the core financial engine and represent upcoming engineering work:
- Database-enforced immutability for posted ledger entries (currently, `ON DELETE RESTRICT` protects parent records from deletion, but does not prevent direct `UPDATE` or `DELETE` on ledger entries; database-enforced append-only behavior via role permissions or triggers remains a future requirement).
- Server-side database triggers for automatic `updated_at` refresh on raw SQL updates outside the ORM.
- Engine-level PostgreSQL row-level security (RLS), if required by the threat model.

## Running Tests

### Backend Test Suite
Configured via `pytest.ini` with 247 automated unit, API, and PostgreSQL integration tests:
```powershell
pytest -q
```
*Result:* **247 passed in 19.65s** (0 warnings).

### Frontend Test Suite
Configured via `vitest` with 22 automated unit and component integration tests:
```powershell
npm --prefix frontend run test
```
*Result:* **22 passed across 5 test files in 4.85s** (0 warnings).

## Documentation & AI Usage Log

- **Architecture Details:** See [`docs/architecture.md`](docs/architecture.md) for domain service design and invariant specifications.
- **AI Usage Log:** See [`PROMPTS.md`](PROMPTS.md) for the complete, verbatim prompt history and independent audit trail.

## API Documentation

When the backend is running: http://localhost:8000/docs

## Live URL

*To be added after deployment.*

## Limitations

*To be documented as development progresses.*
