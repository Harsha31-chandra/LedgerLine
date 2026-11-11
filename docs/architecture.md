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
   Customer account balances must not drop below zero (`balance >= 0` check constraint enforced on customer accounts; `SYSTEM_CLEARING` permits negative settlement balances while strictly reconciling with its ledger journals).
5. **Exactly-Once Execution**:
   Replaying a request with the same `(user_id, idempotency_key)` returns the identical original result without moving money again.

## Database Schema & Migration State

The foundational relational schema is defined by eight SQLAlchemy 2.x declarative models and compiled via Alembic into baseline migration `7717a26bd3d3_initial_schema` ([`backend/migrations/versions/7717a26bd3d3_initial_schema.py`](../backend/migrations/versions/7717a26bd3d3_initial_schema.py)) and clearing debit balance migration `27022f5fc965_allow_clearing_debit_balance` ([`backend/migrations/versions/27022f5fc965_allow_clearing_debit_balance.py`](../backend/migrations/versions/27022f5fc965_allow_clearing_debit_balance.py)).

### Verified Migration Status
- **Target Database:** Verified and applied exclusively to the isolated test database `ledgerline_test` (`localhost:5432`).
- **Commands:**
  - Baseline: `python -m alembic -c backend\alembic.ini upgrade head` (Result: `Running upgrade  -> 7717a26bd3d3, initial schema`).
  - Clearing Debit Balance: `alembic -c backend/alembic.ini upgrade head` (Result: `Running upgrade 7717a26bd3d3 -> 27022f5fc965, allow clearing debit balance`).
- **Table Verification:** `ledgerline_test` contains all eight application domain tables plus `alembic_version` (storing revision `27022f5fc965`).
- **Schema Drift Check:** Verified clean via `python -m alembic -c backend\alembic.ini check` (`No new upgrade operations detected`).
- **Environment Isolation:** All migrations were applied exclusively to `ledgerline_test`. The development database (`ledgerline`) was not targeted by migrations.

### Domain Tables Overview
1. **`users`**: Authenticated principals with system roles (`ADMIN`, `HOLDER`, `AUDITOR`), unique indexed email, and Argon2id password hash (`VARCHAR(255)` storing PHC-formatted hashes). See [`THREATS.md`](../THREATS.md) for cryptographic parameters and storage format.
2. **`sessions`**: Server-managed, revocable login sessions with unique indexed `token_hash`, expiry, and activity tracking.
3. **`accounts`**: Financial accounts with integer paise balance cache, unique indexed account number, and status (`ACTIVE`, `FROZEN`, `CLOSED`).
4. **`account_memberships`**: User-to-account entitlements (`OWNER`, `OPERATOR`, `VIEWER`) with compound unique constraint `(user_id, account_id)` preventing BOLA/IDOR vulnerabilities.
5. **`transactions`**: Business intent headers tracking reference, operation type (`DEPOSIT`, `WITHDRAWAL`, `TRANSFER`), and lifecycle status (`PENDING`, `POSTED`, `REJECTED`).
6. **`ledger_entries`**: Double-entry financial journal lines (`DEBIT`, `CREDIT`, positive `amount_paise`). Foreign keys to `accounts` and `transactions` specify `ondelete='RESTRICT'`, which protects referenced parent records from deletion while ledger entries reference them. Protected by PostgreSQL engine-level triggers `trg_ledger_entries_immutability` and `trg_ledger_entries_truncate` prohibiting all UPDATE, DELETE, and TRUNCATE operations, combined with database role privilege restrictions on runtime application role `ledgerline_app`.
7. **`idempotency_records`**: Exactly-once execution records with compound unique constraint `(user_id, idempotency_key)`, canonical request hash, and cached response payload.
8. **`audit_events`**: Append-only security and operational audit trail with composite action/time index and `SET NULL` on actor user reference.

## Authentication, Session & HTTP API Foundation

The authentication and session management layer is implemented across `backend/app/services/auth_service.py`, `backend/app/schemas/auth.py`, `backend/app/api/auth.py`, `backend/app/api/deps.py`, `backend/app/core/csrf.py`, and `backend/app/core/rate_limit.py`:

- **User Registration (`POST /auth/register`):** Server-enforced role assignment (`UserRole.HOLDER`), lowercase email normalization, safe password length boundaries (`1-128` chars; formal password policy is a separate requirement), and Argon2id password hashing. Reliable duplicate-email constraint detection inspects driver diagnostics (PostgreSQL SQLSTATE `23505` on `ix_users_email` / SQLite `SQLITE_CONSTRAINT_UNIQUE` on `users.email`), rolls back explicitly, and converts collisions to `UserAlreadyExistsError` (HTTP 409) while re-raising unrelated integrity errors unchanged. Client payload forbids extra attributes (`extra='forbid'`) preventing privilege escalation. Protected by rate limiting (default: `5/minute`).
- **Timing Side-Channel Mitigation & Login (`POST /auth/login`):** Credential verification executes a dummy Argon2id verification with identical RFC 9106 parameters when an unknown email is supplied, mitigating timing-based account enumeration (without guaranteeing constant-time execution across variable system environments). Successful login establishes a server session and sets an `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` (dynamic based on `cookie_secure`) session cookie (`ledgerline_session`). Raw tokens are never exposed in response JSON or logs. Protected by rate limiting (default: `10/minute`).
- **Cryptographic Session Tokens:** 256-bit CSPRNG opaque tokens generated via `secrets.token_urlsafe(32)`. The raw token is returned to the client exclusively through the `Set-Cookie` header; the database persists only its SHA-256 digest (`token_hash`).
- **Session Validation & Revocation (`POST /auth/logout`, `GET /auth/me`):** Timezone-aware UTC expiration check with strictly positive fixed TTL (`settings.session_ttl_minutes > 0`, explicitly rejecting booleans, floats, zero, and negative values). Soft revocation records `revoked_at` timestamp. `POST /auth/logout` revokes the session and clears the cookie with matching attributes idempotently. `GET /auth/me` returns the authenticated `UserResponse`.
- **FastAPI Authentication Dependencies (`backend/app/api/deps.py`):**
  - `get_current_session`: Extracts the session cookie, computes SHA-256 digest, and validates against the database via `validate_session`. Rejects missing, expired, revoked, or inactive sessions with generic HTTP 401.
  - `get_current_user`: Resolves the authenticated `User` from the validated session.
  - `get_db`: Re-exported session dependency managing unit-of-work lifecycle.
- **CSRF Defense Middleware (`backend/app/core/csrf.py`):**
  - Evaluates all state-changing HTTP requests (`POST`, `PUT`, `PATCH`, `DELETE`).
  - Enforces exact origin semantics against configured `settings.cors_origins_list` with canonical normalization (`scheme://hostname[:port]`, default ports omitted, lowercased, and bracketed IPv6 literals preserved per RFC 3986).
  - Explicitly rejects `Origin: null`, unsupported schemes, user-info components (`user@host`), paths/queries in Origin headers, and malformed inputs (invalid IPv6, out-of-range ports) with HTTP 403, safely catching `ValueError` to prevent 500 errors.
  - Never trusts client-controlled `Host` or request headers for origin determination, mitigating Host-header injection and DNS rebinding attacks.
  - Passes safe read methods (`GET`, `HEAD`, `OPTIONS`) and integrates seamlessly with `CORSMiddleware`.
- **Role-Based Access Control & Account Authorization (`backend/app/services/authorization_service.py`, `backend/app/api/deps.py`):**
  - **Global Role Guards:** `require_global_role(*roles)` dependency factory with convenience wrappers `require_admin`, `require_auditor`, and `require_holder`.
  - **Account-Level Entitlements:** `get_authorized_account(action)` dependency factory (aliased as `require_account_read`, `require_account_operate`, `require_account_manage`) enforcing per-account membership verification.
  - **Permission Matrix & Conflict Resolution:** Combines global roles (`ADMIN`, `HOLDER`, `AUDITOR`) and account memberships (`OWNER`, `OPERATOR`, `VIEWER`). Global AUDITOR read-only policy strictly overrides membership role to prevent privilege escalation.
  - **BOLA/IDOR Prevention:** Non-members querying an account UUID receive HTTP 404 (`Account not found`) rather than HTTP 403, preventing account existence discovery. Mutating operations are rejected on `FROZEN` or `CLOSED` accounts.
- **Production Configuration Safeguards:** Production environment (`app_env='production'`) fails closed at configuration startup if `session_secret` is default, placeholder, or shorter than 32 characters.

## Financial Core Services, Double-Entry Posting & Concurrency Architecture

Implemented in `backend/app/services/`:

1. **Account Service (`backend/app/services/account_service.py`):**
   - Coordinates creation, retrieval, listing, detail updates, and lifecycle transitions.
   - `create_account`: Restricted to `ADMIN`. Atomically registers the account and establishes the initial `OWNER` membership row in the same transaction.
   - `get_account_by_id`: Implements anti-IDOR defense by returning 404 for unowned accounts.
   - `list_user_accounts`: Restricts query results strictly to accounts where the caller possesses an active membership (anti-IDOR / tenant isolation).
   - `list_all_accounts`: Provides administrative system account registry access (`GET /admin/accounts`), restricted exclusively to `ADMIN` users via `SystemAction.VIEW_ALL_ACCOUNTS`. Returns all non-system customer accounts across all holders while strictly excluding `SYSTEM_CLEARING`.
   - **Separation of Administrative Oversight from Operational Access:** Administrative registry visibility grants oversight into all customer accounts and their status, but deliberately does NOT grant operational membership (`AccountAction.OPERATE`, e.g. deposits, withdrawals, transfers) or private statement access. Admins cannot move customer funds without explicit membership credentials.
   - `change_account_status`: Admin-controlled transitions (`ACTIVE`, `FROZEN`, `CLOSED`). Status changes on `SYSTEM_CLEARING` are prohibited (`AccountStatusError`, HTTP 403). Emits audit events.
   - `get_or_create_system_clearing_account`: Manages the `SYSTEM_CLEARING` account (0 opening balance) required for balanced double-entry external money operations. Concurrency-safe: uses nested transaction savepoints (`begin_nested()`) to catch `IntegrityError` without session abort on simultaneous worker initialization races.

2. **Ledger Service (`backend/app/services/ledger_service.py`):**
   - Authoritative financial engine enforcing balanced journal entries.
   - `post_ledger_transaction`:
     - Validates positive minor-unit integer amounts (`amount_paise > 0`).
     - Checks currency equivalence across debit and credit counterparties.
     - Creates the logical `Transaction` header with `POSTED` status.
     - Creates balanced `DEBIT` and `CREDIT` `LedgerEntry` lines.
     - Verifies mathematical balance invariant: $\sum \text{Debits} == \sum \text{Credits}$. Discrepancies raise `UnbalancedLedgerError`.
     - Atomically updates and flushes cached `Account.balance` snapshots for both counterparties within the calling unit of work. Customer accounts enforce non-negative balances; `SYSTEM_CLEARING` permits debit settlement balances.
   - `reconcile_account_balance`: Computes $\sum \text{Credits} - \sum \text{Debits}$ from all posted ledger lines and verifies parity with `Account.balance`.

3. **Transaction Service (`backend/app/services/transaction_service.py`):**
   - Coordinates end-to-end deposits, withdrawals, transfers, and statements.
   - **Pessimistic Row-Level Locking:** Acquires exclusive locks via `select(Account).where(Account.id == ...).with_for_update().execution_options(populate_existing=True)`. The `populate_existing=True` option guarantees SQLAlchemy synchronizes in-memory object attributes with the fresh database row returned upon unblocking.
   - **Deterministic Deadlock Prevention:** Sorts account UUIDs before acquiring locks (`min(id1, id2)` then `max(id1, id2)`), eliminating circular wait conditions across concurrent transfers.
   - **Re-check Under Lock:** Balance and active status are verified strictly under the exclusive row lock, preventing concurrent overdrafts.
   - **Clearing Account Pairing:** Deposits debit `SYSTEM_CLEARING` and credit customer account; withdrawals debit customer account and credit `SYSTEM_CLEARING`. Transfers debit source and credit destination directly. Prohibits `SYSTEM_CLEARING` from being targeted or sourced in peer-to-peer transfers (`ClearingAccountTransferError`, HTTP 400).
   - `get_transaction_by_id`: Enforces active membership on at least one involved account, returning 404 for non-members (including `ADMIN`/`AUDITOR` without membership per PROMPT-030). Safely compares both `UserRole` enums and raw database string roles.
   - `get_account_statement`: Returns chronological ledger lines with transaction references, timestamps, and balance snapshots.

4. **Idempotency Service (`backend/app/services/idempotency_service.py`):**
   - User-scoped idempotency key management (`(user_id, idempotency_key)` unique constraint).
   - Canonical SHA-256 request payload hashing (`compute_request_hash`).
   - Atomic reservation before execution. Detects in-flight requests (`IdempotencyInFlightError`) and payload collisions (`IdempotencyCollisionError`).
   - Row-level pessimistic locking on lookup (`SELECT ... FOR UPDATE`), preventing concurrent workers from racing on expired key reclamation under PostgreSQL READ COMMITTED isolation.
   - Enforces UTC key expiration (`expires_at <= now`). Expired completed or abandoned in-flight records are safely reclaimed in-place without key collisions.
   - Caches completed response payloads for safe identical replays without financial re-execution.

5. **Audit Service (`backend/app/services/audit_service.py`):**
   - Enrolls `AuditEvent` records directly in the active unit-of-work transaction.
   - Records actor user UUID, client IP, action, entity type/ID, and metadata with sensitive parameter scrubbing.

### Database-Enforced Ledger Immutability, Three-Tier Role Separation & Fail-Closed Runtime Policy

Implemented in migration `c18f3a8b9e10_enforce_ledger_entries_immutability` and verified by `tests/integration/test_ledger_immutability_postgres.py` and `tests/unit/test_database.py`:

1. **PostgreSQL Immutability Triggers:**
   - **Row-Level Immutability Trigger (`trg_ledger_entries_immutability`):** Attached `BEFORE UPDATE OR DELETE ON ledger_entries FOR EACH ROW`. Invokes PL/pgSQL function `protect_ledger_entries_immutability()` which raises an exception with SQLSTATE `20000` on any UPDATE or DELETE attempt, rejecting the statement immediately.
   - **Statement-Level Truncate Trigger (`trg_ledger_entries_truncate`):** Attached `BEFORE TRUNCATE ON ledger_entries FOR EACH STATEMENT`. Invokes PL/pgSQL function `protect_ledger_entries_truncate()` which raises an exception with SQLSTATE `20000` on any TRUNCATE attempt.
   - **No Session Variable Bypass:** Avoids insecure custom session parameter checks (e.g. `current_setting('ledgerline.allow_ledger_maintenance')`). Trigger protection applies strictly to all execution paths.

2. **Three-Tier Database Role Separation & Least Privilege:**
   - **Bootstrap Administrator Role (`ledgerline`):** Configured as the PostgreSQL cluster provisioning role (`POSTGRES_USER` in Docker). Dedicated exclusively to cluster bootstrapping, creating databases, and provisioning initial operational roles. Never used for application runtime or routine migrations.
   - **Routine Migration / Schema-Owner Role (`ledgerline_migrator`):** Dedicated least-privilege migration role created with `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`. Owns the `public` schema and all domain tables and functions (`ALTER SCHEMA public OWNER TO ledgerline_migrator`). Alembic migrations execute routine DDL under `ledgerline_migrator` via `MIGRATION_DATABASE_URL` without superuser or role-creation privileges.
   - **Application Runtime Role (`ledgerline_app`):** Dedicated non-superuser role created with `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`. Strictly granted `SELECT, INSERT` on `ledger_entries` and `audit_events`, plus `SELECT, INSERT, UPDATE, DELETE` on mutable operational tables (`users`, `sessions`, `accounts`, `account_memberships`, `transactions`, `idempotency_records`). Holds zero `UPDATE`, `DELETE`, or `TRUNCATE` privileges on the ledger.
   - **Table Ownership Boundary:** `ledgerline_app` does not own `ledger_entries` or any other domain table. PostgreSQL strictly prohibits non-owners from disabling (`ALTER TABLE ... DISABLE TRIGGER`), dropping (`DROP TRIGGER`), or reassigning ownership (`ALTER TABLE ... OWNER TO`) of database triggers, preventing malicious or accidental tampering even under arbitrary SQL execution (rejected with SQLSTATE `42501: must be owner of table ledger_entries`).

3. **Environment-Aware Fail-Closed Runtime Database Configuration:**
   - **Fail-Closed Validation (`backend/app/core/database_url.py`):** `validate_runtime_database_url` rigorously parses and validates application database connection strings before engine creation across all deployment environments.
   - **Local / Test Environments (`app_env in ('development', 'test', 'local')`):**
     - Target database restricted to approved local databases: `APPROVED_RUNTIME_DATABASES = frozenset({"ledgerline", "ledgerline_test"})`.
     - Host restricted to local loopback addresses: `APPROVED_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})`.
     - Port restricted to standard PostgreSQL port `5432` (or explicitly configured `DB_ALLOWED_PORTS`).
     - SQLite in-memory (`:memory:`) permitted exclusively for isolated unit test overrides; file-based SQLite is rejected.
   - **Production Environment (`app_env in ('production', 'prod')`):**
     - Host must be explicitly allowlisted via `DB_ALLOWED_HOSTS`. A missing or empty allowlist fails closed immediately.
     - Database name must be explicitly allowlisted via `DB_ALLOWED_DATABASES`. A missing or empty allowlist fails closed immediately.
     - Test database targets (`ledgerline_test`, `*_test`, `test_*`) are unconditionally prohibited in production environments.
     - SQLite (even in-memory) is strictly prohibited.
   - **Universal Role Least Privilege (All Environments):**
     - Runtime connections must strictly use dedicated unprivileged role `APPROVED_RUNTIME_ROLE = "ledgerline_app"`.
     - Privileged, superuser, bootstrap, and migration roles are unconditionally prohibited: `PROHIBITED_RUNTIME_ROLES = frozenset({"ledgerline", "ledgerline_migrator", "postgres", "root", "admin"})`.
   - **Zero Fallback (`backend/app/core/database.py`):** `create_app_engine()` resolves `target_url = database_url if database_url is not None else settings.app_database_url` and validates it with `validate_runtime_database_url`. The application runtime will never fall back to a privileged migration URL or superuser credentials.
   - **Fresh Initialization Default Privileges (`scripts/init_db.sql`):** Configures `ALTER DEFAULT PRIVILEGES FOR ROLE ledgerline_migrator IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ledgerline_app;` and `GRANT USAGE, SELECT ON SEQUENCES TO ledgerline_app;`. Migration `c18f3a8b9e10` explicitly enforces `REVOKE UPDATE, DELETE, TRUNCATE ON ledger_entries, audit_events FROM ledgerline_app;`, ensuring newly created domain tables permit normal application operations while immutable tables remain strictly append-only.

4. **Isolated Test-Administration Maintenance Mechanism:**
   - Production and runtime application roles have zero ledger modification or maintenance privileges.
   - Integration tests requiring fixture cleanup connect via the isolated test schema owner (`ledgerline_migrator`) using an isolated test-administration connection (`_cleanup_test_records` / `_cleanup_database`). The owner connection temporarily disables `trg_ledger_entries_immutability`, deletes isolated test rows matching specific test fixture references, and re-enables the trigger in a strict `try...finally` block.
   - The runtime application role `ledgerline_app` cannot execute this cleanup mechanism because PostgreSQL rejects `ALTER TABLE ... DISABLE TRIGGER` with `42501: must be owner of table ledger_entries`.

5. **Reversal Architecture:**
   - Financial adjustments and reversals must strictly be represented as new compensating transactions and new append-only ledger entries.
   - Direct mutation or deletion of historical ledger entries is prohibited by both the database engine and the domain architecture.

### Database-Enforced Timestamp Consistency Architecture

Implemented in migration `d4a72e81bc34_enforce_database_updated_at_triggers` and verified by `tests/integration/test_timestamp_consistency_postgres.py`:

1. **Server-Side Timestamp Enforcement (`update_updated_at_column`):**
   - **Reusable Trigger Function:** PL/pgSQL function `update_updated_at_column()` attached `BEFORE UPDATE` to all mutable tables possessing an `updated_at` column (`accounts`, `users`, `transactions`).
   - **Guaranteed `updated_at` Freshness:** Automatically assigns `NEW.updated_at = clock_timestamp()` on any row modification, eliminating reliance on client-side or ORM `onupdate` hooks and guaranteeing freshness under direct SQL UPDATEs.
   - **`created_at` Immutability:** Explicitly sets `NEW.created_at = OLD.created_at`, physically preventing backdating or mutation of record creation timestamps during UPDATE statements.
   - **No-Op Update Preservation:** Evaluates `IF (NEW IS NOT DISTINCT FROM OLD) THEN RETURN OLD; END IF;`, ensuring that statements updating rows to identical values do not generate spurious timestamp increments.
   - **Client-Side Forgery Override:** Any client-supplied or forged `updated_at` value in an UPDATE statement is unconditionally overridden by PostgreSQL's authoritative `clock_timestamp()`.
   - **Timezone Awareness:** All timestamps are stored as PostgreSQL `TIMESTAMPTZ` (UTC).

2. **Table Inclusion & Exclusion Policy:**
   - **Included Mutable Tables:**
     - `accounts`: Tracks balance cache snapshot updates, status transitions (`ACTIVE`, `FROZEN`, `CLOSED`), and name changes.
     - `users`: Tracks profile modifications, password credential rotations, role adjustments, and activation status changes.
     - `transactions`: Tracks transaction lifecycle transitions (`PENDING` -> `POSTED` / `REJECTED`).
   - **Intentionally Excluded Immutable & Event Tables:**
     - `ledger_entries`: Authoritative double-entry ledger. Strictly append-only. UPDATE, DELETE, and TRUNCATE are physically blocked by `trg_ledger_entries_immutability` and `trg_ledger_entries_truncate` (SQLSTATE `20000`). Adding `updated_at` or update triggers would violate core financial immutability.
     - `audit_events`: Tamper-evident operational audit log. Strictly append-only. Records represent immutable historical events.
     - `account_memberships`: Junction table mapping users to accounts. Rows are created or deleted. No `updated_at` column exists on the model.
     - `sessions`: Authentication session records. Employs discrete event timestamps (`created_at`, `expires_at`, `revoked_at`, `last_activity_at`) rather than a general `updated_at`.
     - `idempotency_records`: Request deduplication cache. Employs `created_at` and `expires_at`.

3. **Role & Privilege Boundary:**
   - The trigger function `update_updated_at_column()` and all associated triggers are owned by `ledgerline_migrator`.
   - The application runtime role `ledgerline_app` does not own any domain tables. Any attempt by `ledgerline_app` to disable (`ALTER TABLE ... DISABLE TRIGGER`), drop, or alter timestamp triggers is rejected with SQLSTATE `42501: must be owner of table`.

## Frontend Architecture (React + TypeScript Production SPA)

The LedgerLine user interface is built as a production-grade single-page application integrating with the backend API:

- **Directory Structure (`frontend/src/`):**
  - **`types/api.ts`**: Strict TypeScript interfaces reflecting FastAPI request and response models (1:1 with Pydantic models: `User`, `Account`, `AccountWithMembership`, `Transaction`, `LedgerEntry`, `AccountStatement`, `AdminStats`, `AdminUser`, `GlobalOverview`, `AuditEvent`, and request schemas).
  - **`api/`**: Centralized HTTP client layer (`client.ts`) and modular service wrappers (`auth.ts`, `accounts.ts`, `transactions.ts`, `admin.ts`). Enforces `credentials: "include"`, standardizes error handling (401, 403, 404, 409, 422, 429), and sets `Idempotency-Key` headers on mutating financial requests.
  - **`context/` & `hooks/`**: `AuthContext` and `useAuth` provide global user session state. Automatically restores sessions on initial mount via `GET /auth/me`. Does not store credentials or tokens in browser storage (`localStorage` / `sessionStorage`).
  - **`components/`**: Presentation components:
    - `Navbar`: Dynamic navigation bar with brand, user identity, role badge, and role-specific shortcuts ("Admin Console", "Auditor Console").
    - `Sidebar`: Tabbed navigation with live ledger status indicator.
    - `ProtectedRoute`: Guards authenticated routes and redirects unauthenticated users to `/login`.
    - `OnboardingWelcome`: Dedicated first-time user welcome screen with SVG vault illustration, feature highlights, and account opening CTA.
    - `AccountOpeningModal`: Interactive modal with live debit card preview, currency selector, and optional ₹10,000 demo initial deposit.
    - `QuickActionModals`: Two-step modal workflows for Deposit, Withdrawal, and Peer-to-Peer Transfer with preset amount pills and double-entry confirmation reviews.
    - `RecentTransactionsTable`: Filterable, searchable, paginated ledger activity table with double-entry inspector modal.
    - `StatementsViewer`: Official chronological account statement viewer with printable layout and zero-sum balance displays.
    - `ProfileSettingsView`: Security settings display confirming HttpOnly session metadata and cryptographic parameters.
    - `Toast`: Global success notification toast.
    - `RoleBadge`, `StatusBadge`, `CurrencyAmount`, `Alert`, and `Modal`.
  - **`pages/`**:
    - `LoginPage`: Email/password form with quick demo credential buttons for assessment evaluation.
    - `RegisterPage`: Full name, email, password verification with automated post-registration login.
    - `DashboardPage`: Command center for HOLDER users displaying 4 financial summary cards, quick actions toolbar, account inventory cards, and recent transactions. Dynamically renders `AuditorDashboardPage` if the authenticated user has the global `AUDITOR` role.
    - `AccountDetailPage`: In-depth account view with balance, operation modals, and chronological statement history.
    - `AdminAccountsPage`: Administrative management console for `ADMIN` users backed by `/admin/accounts`, `/admin/stats`, `/admin/users`, and `/admin/memberships` with three tabs: Accounts Registry (with Status change modal), User Directory (with Membership Assignment modal), and Audit Trail Monitoring.
    - `AuditorDashboardPage`: Regulatory oversight console for `AUDITOR` users backed by `/audit/overview`, `/audit/accounts`, `/audit/transactions`, and `/audit/logs`. Features a prominent Read-Only Safety Banner, global financial overview metrics, and read-only journal inspection. All financial mutation buttons and operational controls are strictly omitted.
    - `NotFoundPage`: 404 fallback page.
  - **`utils/currency.ts`**: Minor-unit conversion (`parseRupeesToPaise`) and currency formatting (`formatPaise`).
    - *Frontend vs. Backend Precision Contract*: The backend database stores monetary amounts using PostgreSQL signed 64-bit `BIGINT` (`MAX_PAISE_AMOUNT = 9,223,372,036,854,775,807n`, $2^{63} - 1$). The frontend uses JavaScript's `number` type for amounts, which is exact only up to `Number.MAX_SAFE_INTEGER` (`9,007,199,254,740,991n`, $2^{53} - 1$, representing ₹90,071,992,547,409.91). To prevent silent precision loss, `parseRupeesToPaise` strictly rejects inputs exceeding `FRONTEND_MAX_SAFE_PAISE` (returning `0`). Furthermore, `formatPaise` uses exact integer arithmetic (`BigInt`) to prevent float-division rounding errors on large safe-integer values.
- **Idempotency Strategy:**
  - Client generates a UUID (`crypto.randomUUID()`) when opening a financial operation modal.
  - Preserves the same idempotency key across retries if a request fails due to network glitch or transient errors, ensuring the server replays safely rather than attempting double-execution.
  - Generates a fresh key only when a new distinct user operation is initiated.
  - Disables submit buttons during active in-flight requests.

## Remaining Engineering Considerations (Implementation Roadmap)

The following architectural and security capabilities are distinguished from the core financial engine and represent scheduled future engineering tasks:

1. **Database-Enforced Immutability for Posted Ledger Entries (Completed):**
   - Implemented in migration `c18f3a8b9e10`, triggers `trg_ledger_entries_immutability` / `trg_ledger_entries_truncate`, and dedicated least-privilege role `ledgerline_app`. Direct SQL UPDATE, DELETE, and TRUNCATE are physically blocked at the PostgreSQL engine level.
2. **Database Trigger for Automatic `updated_at` Refresh (Completed):**
   - Implemented in migration `d4a72e81bc34` via `update_updated_at_column()` on `accounts`, `users`, and `transactions`. Guarantees server-side timestamp updates on direct SQL, preserves `created_at`, overrides client forgery, and prevents spurious bumps on no-op updates.
3. **PostgreSQL Row-Level Security (RLS):**
   - Engine-level RLS policies if required by the eventual multi-tenant threat model beyond application-level authorization in `AccountMembership` and `authorization_service.py`.

---
*For a complete chronological log of all AI-assisted tasks, prompt texts, and audit results, see [`PROMPTS.md`](../PROMPTS.md).*
