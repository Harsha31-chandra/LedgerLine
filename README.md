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

## Database Environment Isolation & Three-Tier Role Separation

LedgerLine strictly isolates development, testing, and migration database environments and enforces three-tier role least privilege:

- **Bootstrap Administrator (`ledgerline`)**: Used exclusively for initial PostgreSQL container provisioning and database creation. Never used for application runtime or routine migrations.
- **Migration & Schema-Owner Role (`ledgerline_migrator`)**: Non-superuser role (`NOSUPERUSER`) that owns the `public` schema and all domain tables/functions. Used by `MIGRATION_DATABASE_URL` for routine Alembic migrations and by `TEST_DATABASE_URL` for test fixture setup.
- **Application Runtime Role (`ledgerline_app`)**: Non-superuser, non-owner role (`NOSUPERUSER`) used by `APP_DATABASE_URL` and `DATABASE_URL`. Strictly granted `SELECT, INSERT` on `ledger_entries` (no `UPDATE`, `DELETE`, `TRUNCATE`). Does not own tables and cannot disable triggers.
- **Environment-Aware Fail-Closed Validation**: `validate_runtime_database_url` verifies connection strings before engine creation. Prohibits privileged roles (`ledgerline`, `ledgerline_migrator`, `postgres`, `root`, `admin`) and requires `ledgerline_app`. In local/test environments, restricts connections to loopback hosts (`localhost`, `127.0.0.1`, `::1`), port 5432, and databases `ledgerline`/`ledgerline_test`. In production (`APP_ENV=production`), requires explicit host and database allowlists (`DB_ALLOWED_HOSTS`, `DB_ALLOWED_DATABASES`), rejects missing allowlists, and strictly blocks test database targets (`*_test`). Engine creation will never silently fall back to privileged migration settings.

## Database Schema & Migration Status

- **Baseline Migration:** `7717a26bd3d3_initial_schema` ([`backend/migrations/versions/7717a26bd3d3_initial_schema.py`](backend/migrations/versions/7717a26bd3d3_initial_schema.py)).
- **Clearing Debit Balance Migration:** `27022f5fc965_allow_clearing_debit_balance` ([`backend/migrations/versions/27022f5fc965_allow_clearing_debit_balance.py`](backend/migrations/versions/27022f5fc965_allow_clearing_debit_balance.py)). Resets `SYSTEM_CLEARING` balance snapshot to 0 and updates `ck_accounts_balance_non_negative` check constraint to `CHECK (balance >= 0 OR account_number = 'SYSTEM_CLEARING')`.
- **Ledger Immutability Migration:** `c18f3a8b9e10_enforce_ledger_entries_immutability` ([`backend/migrations/versions/c18f3a8b9e10_enforce_ledger_entries_immutability.py`](backend/migrations/versions/c18f3a8b9e10_enforce_ledger_entries_immutability.py)). Enforces database-level append-only protection on `ledger_entries` via PL/pgSQL triggers (`trg_ledger_entries_immutability`, `trg_ledger_entries_truncate`), revoking UPDATE/DELETE/TRUNCATE from `ledgerline_app`.
- **Timestamp Consistency Migration:** `d4a72e81bc34_enforce_database_updated_at_triggers` ([`backend/migrations/versions/d4a72e81bc34_enforce_database_updated_at_triggers.py`](backend/migrations/versions/d4a72e81bc34_enforce_database_updated_at_triggers.py)). Attaches `update_updated_at_column()` triggers to mutable tables (`accounts`, `users`, `transactions`), guaranteeing fresh server-side timestamps on direct SQL, preserving `created_at`, overriding client forgery, and suppressing spurious bumps on no-op updates.
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
- **Double-Entry Invariants & Database Immutability:**
  - Every transaction generates balanced `DEBIT` and `CREDIT` entries where $\sum \text{Debits} == \sum \text{Credits}$.
  - System clearing account (`SYSTEM_CLEARING`, 0 opening balance) represents external rail claims/obligations, ensuring total money conservation across every operation: $\sum \text{Customer Balances} + \text{Clearing Balance} == 0$.
  - Customer accounts strictly enforce non-negative balances (`balance >= 0`); `SYSTEM_CLEARING` permits negative settlement balances.
  - Periodic reconciliation audits balance snapshots against posted ledger journals via `reconcile_account_balance` (`is_reconciled=True`).
  - **PostgreSQL Database-Level Immutability:** Row-level `BEFORE UPDATE OR DELETE` trigger `trg_ledger_entries_immutability` and statement-level `BEFORE TRUNCATE` trigger `trg_ledger_entries_truncate` block all updates, deletions, and truncations on `ledger_entries` with SQLSTATE `20000`.
  - **Role Separation & Least Privilege:** Dedicated runtime application role `ledgerline_app` (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`) has only `SELECT, INSERT` on `ledger_entries` (no `UPDATE`, `DELETE`, `TRUNCATE`) and does not own the table, physically preventing trigger tampering or privilege escalation. Routine Alembic migrations run under schema-owner role `ledgerline_migrator` via `MIGRATION_DATABASE_URL` without superuser privileges, while cluster bootstrap is confined to `ledgerline`.
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

The following capability is distinguished from the core financial engine and represents upcoming engineering work:
- Engine-level PostgreSQL row-level security (RLS), if required by the multi-tenant threat model.

## Running Tests

### Security Test Suite
Configured with 67 dedicated automated security tests in `tests/security/` covering BOLA/IDOR, global role barriers, AUDITOR read-only overrides, account membership hierarchy, mass assignment protection (`extra='forbid'`), session lifecycle, inactive user handling, recursive credential scrubbing, and route authorization matrices:
```powershell
pytest tests/security/ -v
```
*Result:* **67 passed in 6.36s** (0 warnings).

### Backend Test Suite
Configured via `pytest.ini` with 387 automated unit, API, security, concurrency, and PostgreSQL immutability/timestamp integration tests:
```powershell
pytest -q
```
*Result:* **387 passed in 49.33s** (0 warnings, 0 failures).

### PostgreSQL Integration Test Suite
Dedicated multi-worker concurrency, database-level immutability triggers, and server-side timestamp consistency tests:
```powershell
pytest -v tests/integration/
```
*Result:* **34 passed in 14.08s** (0 warnings, 0 failures).

### Frontend Test Suite
Configured via `vitest` with 61 automated unit and component integration tests:
```powershell
npm --prefix frontend run test
```
*Result:* **61 passed across 9 test files in 8.43s** (0 warnings, 0 failures).

### Frontend Linter & Build Validation
```powershell
npm --prefix frontend run lint
npm --prefix frontend run build
```
*Result:* **0 errors, 0 warnings across 45 files (oxlint in 139ms)**; **Clean production build in 337ms (tsc -b && vite build)**.

## Five-Minute Hiring Challenge Demonstration Sequence

This step-by-step walkthrough presents the complete system architecture, financial core, and multi-role security boundaries within 5 minutes:

1. **Architecture & Philosophy (Minute 1):** Introduce LedgerLine's core purpose: moving money while mathematically proving conservation via append-only double-entry postings ($\sum \text{Debits} == \sum \text{Credits}$).
2. **Holder Registration & Onboarding (Minute 2):** Navigate to `http://localhost:3000/register`. Register a fresh user. Demonstrate the dedicated First-Time Onboarding screen with the LedgerLine vault illustration.
3. **Account Creation & Demo Credit (Minute 2.5):** Click `Open Your First Account`. Open `Primary Checking` with sample ₹10,000 opening credit. Show confirmed balance and live debit card preview.
4. **Financial Operations & Real-Time Balance (Minute 3):** 
   - Execute a ₹2,500 deposit (Balance updates to ₹12,500).
   - Execute a ₹1,000 withdrawal (Balance updates to ₹11,500).
   - Open a second account `Business Reserve` (with ₹0 initial balance).
   - Transfer ₹1,500 from `Primary Checking` to `Business Reserve`.
5. **Double-Entry Journal & Statements (Minute 3.5):** Open the `Statements` tab. Inspect the chronological ledger entries. Demonstrate zero-sum debit/credit balance proofs ($\Delta = 0$).
6. **Admin Governance Console (Minute 4):** Sign out and log in as `admin@ledgerline.com` / `SecurePass123!`. Navigate to `Admin Console`. Show system metrics, accounts registry, user directory, and membership assignment modal.
7. **Auditor Read-Only Enforcement (Minute 4.5):** Sign out and log in as `auditor@ledgerline.com` / `SecurePass123!`. Show the prominent `Read-Only Compliance Mode Active` banner, system-wide transaction journal, and demonstrate that mutation controls are completely omitted.
8. **Security & Financial Integrity Conclusion (Minute 5):** Summarize database row locks (`SELECT FOR UPDATE`), immutable triggers, and zero-loss guarantees.

## Documentation & AI Usage Log

- **Architecture Details:** See [`docs/architecture.md`](docs/architecture.md) for domain service design and invariant specifications.
- **AI Usage Log:** See [`PROMPTS.md`](PROMPTS.md) for the complete, verbatim prompt history and independent audit trail.

## API Documentation

- **Docker Compose Gateway (Recommended):** [http://localhost:3000/docs](http://localhost:3000/docs) (Swagger UI) and [http://localhost:3000/redoc](http://localhost:3000/redoc) (ReDoc)
- **Standalone Development Server (when running uvicorn on host):** [http://localhost:8000/docs](http://localhost:8000/docs)

## Deployment & Container Orchestration

LedgerLine provides a containerized multi-tier orchestration environment using Docker and Docker Compose (`docker-compose.yml`):
- **Database (`db`)**: PostgreSQL 16.8 on Alpine with named persistent storage (`pgdata`), attached strictly to the internal `db-net` network with zero host port exposure in default/staging configuration.
- **Backend API (`backend`)**: FastAPI ASGI application running under Uvicorn in a non-root container (`python:3.12-slim`), using the restricted `ledgerline_app` runtime role. Connected to `proxy-net` and `db-net`, trusting forwarded proxy headers exclusively from Nginx (`172.28.1.10`). Exposes port 8000 internally.
- **Frontend SPA (`frontend`)**: Multi-stage production build (`node:22-alpine` builder, `nginx:stable-alpine` runner) with static IP `172.28.1.10` on `proxy-net`. Serves bundled client assets on port 3000 and reverse-proxies API routes directly to the backend. Has no access to `db-net`.
- **Migration Runner (`migrator`)**: Isolated one-off container profile (`--profile ops`) on `db-net` connecting via the privileged schema-owner role `ledgerline_migrator`. Migrations are never executed automatically on application startup.
- **Local Dev Database Access (`docker-compose.dev.yml`)**: An optional development override binding PostgreSQL strictly to local loopback (`127.0.0.1:5432`) for running host-level test suites.

### Environment Configuration
Copy `.env.example` to `.env` and configure appropriate secrets:
- `SESSION_SECRET`: Cryptographically random string ($\ge 32$ characters in production/staging).
- `APP_ENV`: `production` for containerized staging deployment (enforces fail-closed allowlists).
- `DB_ALLOWED_HOSTS`: `db` (required when `APP_ENV=production`).
- `DB_ALLOWED_DATABASES`: `ledgerline` (required when `APP_ENV=production`).
- `DB_APP_PASSWORD`: Password for `ledgerline_app` runtime role.
- `DB_MIGRATOR_PASSWORD`: Password for `ledgerline_migrator` migration role.

### Image Build Commands
Build all container images from scratch:
```powershell
docker compose build
```
Or build backend and frontend individually:
```powershell
docker build -t ledgerline-backend ./backend
docker build -t ledgerline-frontend ./frontend
```

### Local Container Startup
Start the application stack in the background:
```powershell
docker compose up -d
```
Verify container health status:
```powershell
docker compose ps
```

### Separate Database Migration Execution
In accordance with three-tier least privilege, database schema migrations must be executed explicitly by an authorized release operator using the `migrator` ops profile:
```powershell
docker compose run --rm migrator
```

### Health Check Verification
Verify operational status across endpoints:
- Frontend Gateway (Nginx Reverse Proxy): `curl -f http://localhost:3000/health`
  *Returns:* `{"status": "healthy", "service": "ledgerline"}`
- Frontend Web Root: `curl -f http://localhost:3000/`
- API Interactive Documentation: [http://localhost:3000/docs](http://localhost:3000/docs)
- Direct Backend Engine (when running standalone uvicorn outside Docker): `curl -f http://localhost:8000/health`
  *Note: Under Docker Compose, backend port 10000 is isolated within the internal bridge network and accessed securely through the Nginx gateway.*

### Stopping Containers Without Data Loss
To stop running containers while safely preserving database volumes and state:
```powershell
docker compose down
```
> ⚠️ **CAUTION:** Never execute `docker compose down -v` unless an intentional wipe of all persistent PostgreSQL database data is explicitly desired.

## Render Free-Tier Deployment Architecture

LedgerLine is prepared for deployment on Render Free Tier using Infrastructure-as-Code blueprint [`render.yaml`](render.yaml) and documented in the step-by-step [Render Deployment Guide](docs/render_deployment_guide.md). The deployment uses a three-service topology:

1. **Frontend Web Service (Docker)**: React SPA served via Nginx 1.26 Alpine.
   - **Dynamic Port**: Listens on `$PORT` assigned by Render (defaults to 10000 on Render, 80 in local Docker Compose).
   - **Same-Origin API Design**: The browser client exclusively accesses the frontend's origin (e.g., `https://ledgerline-frontend.onrender.com`). Nginx reverse-proxies `/auth`, `/me`, `/accounts`, `/transactions`, `/admin`, and `/health` requests to the backend.
   - **Public Suffix List & Cookie Isolation**: Because `onrender.com` is on Mozilla's Public Suffix List, distinct subdomains (`frontend.onrender.com` and `backend.onrender.com`) are cross-site origins. By keeping all browser requests on the same frontend origin, Nginx preserves First-Party `SameSite=Lax` cookie delivery and CSRF origin verification without requiring insecure `SameSite=None` relaxation.
   - **HTTPS SNI Upstream Proxy**: Nginx proxies to the backend's public HTTPS URL configured via `BACKEND_PUBLIC_URL` (e.g. `https://ledgerline-backend.onrender.com`). It validates TLS using `/etc/ssl/certs/ca-certificates.crt`, passes upstream SNI via `proxy_ssl_server_name on;`, and sanitizes any trailing slashes automatically via `18-sanitize-backend-url.envsh`.

2. **Backend Web Service (Docker)**: FastAPI ASGI application running under Uvicorn in a non-root container (`10001:10001`).
   - **Dynamic Port**: Binds to `0.0.0.0:$PORT` (defaults to 10000 on Render and fallback).
   - **Fail-Closed Security**: In production (`APP_ENV=production`), enforces strict database allowlisting (`DB_ALLOWED_HOSTS`, `DB_ALLOWED_DATABASES`), session secret strength ($\ge 32$ chars), `COOKIE_SECURE=true`, and least-privilege runtime role `ledgerline_app`.
   - **Proxy Trust Boundary**: `FORWARDED_ALLOW_IPS` defaults fail-closed (`127.0.0.1,172.28.1.10`). Because Render does not publish static edge proxy IP ranges, trust in arbitrary forwarded headers is withheld to prevent client-IP spoofing.

3. **Managed PostgreSQL Database (Render PostgreSQL)**:
   - Dedicated managed PostgreSQL instance.
   - Accessed by backend services over Render's private internal network (`dpg-xxxxxx-a:5432`).

### Required Render Environment Variables

| Variable | Service | Secret | Format / Description |
|---|---|---|---|
| `APP_ENV` | Backend | No | `production` |
| `PORT` | Backend & Frontend | No | System-injected by Render (e.g. `10000`) |
| `DATABASE_URL` | Backend | Yes | `postgresql://ledgerline_app:<password>@<internal-host>:5432/<db_name>` |
| `MIGRATION_DATABASE_URL` | Backend (Pre-Deploy) | Yes | `postgresql://ledgerline_migrator:<password>@<internal-host>:5432/<db_name>` |
| `DB_ALLOWED_HOSTS` | Backend | No | Render internal host (e.g. `dpg-xxxxxx-a`) |
| `DB_ALLOWED_DATABASES` | Backend | No | Target database name (must not contain `test`) |
| `DB_ALLOWED_PORTS` | Backend | No | `5432` |
| `SESSION_SECRET` | Backend | Yes | High-entropy string $\ge 32$ chars |
| `COOKIE_SECURE` | Backend | No | `true` |
| `CORS_ORIGINS` | Backend | No | Frontend public URL (e.g. `https://ledgerline.onrender.com`) |
| `BACKEND_PUBLIC_URL` | Frontend | No | Backend public URL (e.g. `https://ledgerline-backend.onrender.com`) |

### Operational Considerations & Limitations

- **Free-Tier Cold Starts**: Free Render Web Services automatically spin down after 15 minutes of inactivity. Incoming requests to an inactive service may experience a 50+ second cold-start delay.
- **Render PostgreSQL Free Limitations**: Render free-tier databases expire after 30 days and do not include automated backups.
- **Manual Migration & Role Provisioning Requirement**: Render managed databases provision only a single primary owner. Role separation (`ledgerline_migrator` for DDL, `ledgerline_app` for DML) requires executing an initial provisioning script before the application starts. Migration provisioning has not yet been executed.

## Live URL

*To be added after deployment.*

## Limitations

- **Remote Staging Pending:** While local and staging container orchestration is fully configured, a remote cloud staging deployment (e.g. Render, Railway, AWS ECS) has not yet been provisioned.
- **Production Secrets Management:** Local orchestration reads environment variables from `.env`; integration with a cloud secret manager (AWS Secrets Manager, HashiCorp Vault) is planned for the cloud production release.
