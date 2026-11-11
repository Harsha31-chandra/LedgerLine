# THREATS.md — LedgerLine Security Threat Model

## System Summary

LedgerLine is a simulated internal money-movement system. It processes deposits, withdrawals and account-to-account transfers using double-entry ledger postings. This is an assessment project — no real money or bank connections are involved.

### Deliberately Out of Scope

- Real bank integrations or payment gateways
- Multi-currency support
- Mobile applications
- AI agents or automated trading

## Assets

| Asset | Description |
|-------|-------------|
| Account balances | Integer paise values representing simulated money |
| Ledger entries | Append-only financial postings |
| Credentials | Hashed passwords (Argon2id), session tokens |
| Audit history | Records of all actions and refused attempts |
| Idempotency records | Replay protection keys and stored responses |

## Credential Protection & Password Hashing Architecture

### 1. Algorithm Selection: Argon2id
LedgerLine uses **Argon2id** (via `argon2-cffi`), the state-of-the-art password hashing algorithm recommended by RFC 9106 and OWASP. Argon2id is a hybrid variant that combines:
- **Argon2d** (data-dependent memory access) for maximum resistance against GPU/ASIC-based brute-force and Time-Memory Trade-Off (TMTO) attacks.
- **Argon2i** (data-independent memory access) on the first pass to defend against side-channel cache-timing attacks.

### 2. Parameters & Rationale (RFC 9106)
- **Memory Cost ($m$):** `65,536 KiB` (64 MiB). Memory-hardness is the primary defense against hardware-accelerated cracking rigs. Requiring 64 MiB per hash prevents attackers from packing thousands of parallel attack threads into GPUs or ASICs.
- **Time Cost ($t$):** `3` iterations. Provides sufficient cryptographic diffusion across the memory matrix while maintaining acceptable interactive login latency (~50ms per operation).
- **Parallelism ($p$):** `4` parallel lanes/threads. Utilizes modern multicore server hardware while constraining attacker compute efficiency.
- **Salt Length:** `16` bytes (128 bits). Cryptographically secure random salt generated via CSPRNG per password, preventing rainbow tables and ensuring identical passwords yield completely distinct hashes.
- **Hash Output Length:** `32` bytes (256 bits).

### 3. Password-Hash Storage Format
Hashes are serialized in the standard Password Hashing Competition (PHC) string format:
```text
$argon2id$v=19$m=65536,t=3,p=4$<base64-salt>$<base64-hash>
```
This format is self-describing, encapsulating the algorithm version, parameters, salt, and digest in a single string (~97 characters). It is stored in `users.password_hash` (`VARCHAR(255)`), leaving ample headroom for future parameter adjustments.

### 4. Verification Behavior
- Implemented via `verify_password(plain_password, hashed_password) -> bool` in `backend/app/core/security.py`.
- Employs constant-time internal comparisons to avoid timing side-channels during hash verification.
- **Fail-Closed:** Returns `False` for mismatched passwords, malformed hash strings, empty inputs, or non-string data types. Never raises unhandled exceptions.
- **Decoupled from User Lookup:** The password verification utility performs no database lookups or user existence checks.

### 5. Authentication Service & Timing Attack Mitigation
- Implemented in `backend/app/services/auth_service.py` (`authenticate_user`).
- **Timing Side-Channel Mitigation:** When an unregistered or non-existent email is queried, `authenticate_user` executes `verify_password(password, DUMMY_ARGON2_HASH)` against a precomputed, parameter-compatible Argon2id dummy hash. This defense substantially mitigates coarse timing discrepancies by ensuring non-existent accounts undergo Argon2id cryptographic verification rather than failing fast. However, this mitigates a timing side channel but does *not* guarantee constant-time authentication across variable system, garbage collection, database, or network layers. (No formal timing benchmark has been claimed or conducted).
- **Generic Error Responses:** Raises a generic `AuthenticationError("Invalid email or password")` uniformly for non-existent users, wrong passwords, and malformed emails.
- **Inactive Account Enforcement:** Users with `is_active = False` are rejected with `InactiveUserError`.

### 6. Session Lifecycle & Token Security Architecture
- Implemented in `backend/app/services/auth_service.py` (`create_session`, `validate_session`, `revoke_session`, `revoke_all_user_sessions`) and `backend/app/config.py` (`Settings`).
- **Cryptographic Randomness:** Session tokens are generated using Python's CSPRNG `secrets.token_urlsafe(32)`, yielding 256 bits of high-entropy randomness encoded as 43 URL-safe base64 characters.
- **Hash-Only Storage:** Plaintext tokens are returned to the caller exactly once upon creation and are never logged or stored in the database. The database stores strictly a SHA-256 digest (`token_hash = hashlib.sha256(raw_token.encode()).hexdigest()`, 64 hex chars) matching `Session.token_hash`.
- **Session Validation:** The incoming token is hashed with SHA-256 before database lookup. Validation fails closed if:
  1. The token hash does not match any session (`SessionNotFoundError`).
  2. The session has been revoked (`SessionRevokedError`).
  3. The session has expired (`SessionExpiredError`).
  4. The associated user account is deactivated (`InactiveUserError`).
- **Strict Positive TTL Enforcement:** Session TTL must be a strictly positive integer (`> 0`). Booleans (`True`/`False`), floats (e.g. `14.5`, `14.0`), zero, negative values, and non-numeric types are explicitly rejected at both configuration initialization (`Settings.session_ttl_minutes`) and during runtime session creation (`create_session(..., ttl_minutes=...)`). Valid positive integer strings loaded from environment variables are safely converted and supported.
- **Fixed Expiry Policy:** Configurable session TTL (defaulting to `settings.session_ttl_minutes = 1440` minutes / 24 hours) using timezone-aware UTC timestamps. Sliding window expiration is deliberately deferred.
- **Production Secret Safeguards:** In production environments (`app_env` set to `production` or `prod`), `Settings` fails closed upon initialization if `session_secret` is unset, uses known placeholders (`change-me-to-a-random-string`), or is shorter than 32 characters, preventing insecure deployments without requiring external secret managers. Development environments permit the placeholder for local developer workflow.
- **Audit-Preserving Revocation:** Revocation records `session.revoked_at = datetime.now(timezone.utc)` without deleting session records, preserving historical auditability. Repeated revocation calls are idempotent.

### 7. Registration & Role Escalation Defense
- Implemented in `backend/app/services/auth_service.py` (`register_user`) and `backend/app/schemas/auth.py` (`UserRegisterRequest`).
- **Role Assignment:** Public registration strictly assigns `UserRole.HOLDER` server-side.
- **Privilege Escalation Prevention:** `UserRegisterRequest` sets `extra='forbid'`, ensuring clients cannot inject `role`, `is_active`, or any other administrative attributes.
- **Email Validation & Normalization:** Emails are normalized (`strip().lower()`) and checked against a pragmatic format pattern (not a full RFC 5322 parser) consistently between schemas and service functions.
- **Reliable Duplicate-Email Constraint Detection:** In addition to proactive existence checks, `register_user` catches database `IntegrityError` upon `db.commit()` and inspects driver-specific diagnostics (PostgreSQL SQLSTATE `23505` with constraint `ix_users_email` or `users.email` / SQLite `SQLITE_CONSTRAINT_UNIQUE` targeting `users.email`). When an email collision is identified, an explicit database rollback is executed before raising `UserAlreadyExistsError`. Unrelated integrity errors (such as check constraint violations or unique violations on other tables) trigger rollback and are re-raised unchanged.
- **Password Boundaries & Policy Distinction:** Safe input length boundaries are enforced (`min_length=1, max_length=128`). No arbitrary minimum length or complexity rules are invented in the application layer; the hashing layer enforces that passwords cannot be empty. A formal password policy (e.g. minimum length, character composition rules, breach dictionary checks) remains a separate future requirement.
- **Sensitive Attribute Exclusion:** Response schemas (`UserResponse`, `SessionResponse`) explicitly omit `password_hash` and `token_hash`.

### 8. Limitations & Residual Risks (Deferred Capabilities)
- **Denial-of-Service (DoS) via Resource Exhaustion:** Concurrent unauthenticated login floods targeting Argon2id are mitigated at the single-instance layer via `slowapi` rate limiting (`10/minute` on login, `5/minute` on registration). However, in-memory rate limiting is process-local and does not provide cluster-wide distributed throttling across multiple application worker processes.
- **Plaintext in Memory:** Plaintext passwords and raw session tokens briefly reside in process memory during verification and session creation. Sensitive fields are excluded from Pydantic response models and are never logged or echoed in HTTP responses.
- **Role-Based Access Control (RBAC):** Server-side RBAC and account-level authorization implemented in `backend/app/services/authorization_service.py` and `backend/app/api/deps.py`. Enforces global roles (ADMIN, HOLDER, AUDITOR), membership roles (OWNER, OPERATOR, VIEWER), AUDITOR read-only overrides, and anti-IDOR protections.
- **Formal Password Policy (Deferred):** Safe input length boundaries (`1-128` characters) are enforced; a comprehensive password composition and breach dictionary policy remains a separate future requirement.

### 9. HTTP Authentication, Cookie Security, CSRF Defense & Rate Limiting Architecture

Implemented across `backend/app/api/auth.py`, `backend/app/api/deps.py`, `backend/app/core/csrf.py`, `backend/app/core/rate_limit.py`, and `backend/app/config.py`.

#### A. Secure Session Cookies
- **Cookie Name:** `ledgerline_session` (configurable via `Settings.session_cookie_name`).
- **`HttpOnly = True`:** Prohibits client-side scripts (JavaScript) from accessing or extracting the raw session token via `document.cookie`, mitigating XSS-based session token exfiltration.
- **`SameSite = "lax"`:** Restricts cookie transmission on cross-site requests. Browsers withhold the session cookie on cross-site sub-requests (such as `<img>`, `<iframe>`, or cross-site AJAX/fetch `POST` requests), while permitting it on safe top-level navigations (such as following a link).
- **`Secure = settings.cookie_secure`:** In production and staging environments (`cookie_secure = True`), the browser will only transmit the session cookie over HTTPS, mitigating cleartext interception on unencrypted networks. Local development permits `Secure = False` for HTTP testing.
- **`Path = "/"`:** Scope restricted to the entire application origin.
- **`Max-Age` / Expiration:** Computed dynamically from `settings.session_ttl_minutes * 60` seconds, ensuring browser cookie expiration aligns with server-side session expiration.
- **Token Absence from JSON:** The raw 256-bit CSPRNG token is returned exclusively through the HTTP `Set-Cookie` header. It is never included in JSON response bodies, query parameters, error responses, or logs.
- **Idempotent Cookie Deletion:** `POST /auth/logout` clears the session cookie using exact matching attributes (`path="/"`, `httponly=True`, `samesite="lax"`, `secure=settings.cookie_secure`) and revokes the session record in the database. Missing, malformed, or already-revoked sessions are handled gracefully without errors.

#### B. CSRF Defense (`CSRFProtectMiddleware`)
Because authentication relies on browser cookies, LedgerLine enforces strict origin-based CSRF defenses:
- **Scope:** Evaluates all incoming state-changing HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`). Safe read-only methods (`GET`, `HEAD`, `OPTIONS`) bypass origin verification.
- **Strict Configured Origin Enforcement (SEC-001 Mitigation):** The trusted-origin whitelist is populated exclusively from configured allowed origins (`settings.cors_origins_list`). The middleware **never** derives trusted origins from incoming `request.base_url`, `request.url.netloc`, or the client-controlled `Host` header. This prevents Host-header injection, DNS rebinding, and origin-poisoning CSRF bypasses.
- **Exact Canonical Origin Semantics:** Both configured allowed origins and incoming request origins/referers are normalized using canonical origin semantics (`scheme://hostname[:port]`):
  - Scheme is strictly validated (`http` or `https`).
  - Hostname is validated and lowercased. Valid IPv6 address literals retain their square brackets per RFC 3986 (`http://[::1]:8000`, `https://[2001:db8::1]:8443`) via `ipaddress.IPv6Address` verification.
  - Port access is protected against `ValueError` (catching non-integer ports e.g. `:abc`, out-of-range ports e.g. `:99999`, `:0`, `:-1`, and trailing colons `localhost:`), rejecting malformed port specifications safely.
  - Default ports (`80` for HTTP, `443` for HTTPS) are canonicalized and omitted. Non-default ports within valid range (`1-65535`) are preserved.
  - Wildcards (`*`) are disallowed and rejected.
- **Strict Origin Syntax & Input Rejection (SEC-002 & SEC-005 Mitigations):**
  - Origin headers are strictly validated against RFC 6454 serialized origin syntax: user-information components (`user@host`, `user:pass@host`), subpaths, query strings, and fragments are explicitly rejected.
  - Opaque origins (`Origin: null`) from sandboxed iframes, redirects, or local data URLs are explicitly rejected with HTTP 403.
  - Malformed or unsupported origins/referers (e.g. invalid IPv6 brackets `http://[invalid-bracket`, out-of-range ports, or unbracketed IPv6) are safely caught without throwing unhandled exceptions, returning HTTP 403 (`{"detail": "CSRF verification failed: untrusted origin"}` or `{"detail": "CSRF verification failed: untrusted referer"}`), preventing unhandled 500 errors.
- **Origin Precedence:** If `Origin` is present, it is evaluated strictly. An untrusted `Origin` cannot be bypassed by providing a legitimate `Referer`.
- **Referer Fallback:** If `Origin` is missing, the origin component of `Referer` is extracted, canonicalized, and compared against the trusted-origin whitelist.
- **Fail-Closed Rejection:** If `Origin` and `Referer` are both missing, empty, or untrusted, the middleware halts execution immediately and returns HTTP 403 Forbidden.
- **Middleware Precedence:** Configured in `backend/app/main.py` such that `CORSMiddleware` executes outermost to handle browser preflight `OPTIONS` requests before `CSRFProtectMiddleware` inspects request bodies.
- **Limitations:** Origin validation requires standard browser behavior. Automated clients (e.g. test suites or third-party API clients) executing state-changing endpoints must include an allowed `Origin` or `Referer` header.

#### C. Rate Limiting (`slowapi`)
- **Scope & Limits:** Applied to public unauthenticated authentication endpoints:
  - `POST /auth/register`: Default `5/minute` (`settings.rate_limit_register`).
  - `POST /auth/login`: Default `10/minute` (`settings.rate_limit_login`).
- **Key Function:** Client IP address via `slowapi.util.get_remote_address`.
- **Response:** Exceeded limits trigger `rate_limit_exceeded_handler`, returning HTTP 429 Too Many Requests with a generic error payload: `{"detail": "Too many requests. Please try again later."}`.
- **Privacy & Security:** Rate-limiting messages do not reveal account existence, user status, or validation details.
- **Limitation:** The current implementation uses `slowapi`'s default in-memory backend. Rate-limit counters are stored in local process memory and are not shared across multiple Uvicorn workers or distributed server nodes. A centralized store (such as Redis) is required for horizontally scaled deployments.

#### D. Authentication Dependencies (`backend/app/api/deps.py`)
- **`get_current_session`:** Extracts `ledgerline_session` from incoming cookies. Returns `None` if missing. If present, calls `validate_session(db, raw_token)`:
  - Validates SHA-256 token hash against `sessions` table.
  - Rejects expired sessions (`SessionExpiredError` -> HTTP 401).
  - Rejects revoked sessions (`SessionRevokedError` -> HTTP 401).
  - Rejects deactivated users (`InactiveUserError` -> HTTP 401).
  - Rejects unrecognized tokens (`SessionNotFoundError` -> HTTP 401).
- **`get_current_user`:** Depends on `get_current_session`. If session is missing or invalid, raises HTTP 401 (`{"detail": "Not authenticated"}`). If valid, returns the associated `User` model instance.
- **Uniform HTTP 401 Responses:** All session validation failures return HTTP 401 with generic, safe error details (`"Not authenticated"`, `"Session has expired"`, `"Session has been revoked"`, `"User account is inactive"`), preventing internal stack trace disclosure.

### 10. Role-Based Access Control (RBAC) & Account Authorization Architecture

Implemented in `backend/app/services/authorization_service.py` and `backend/app/api/deps.py`:

#### A. Global Roles vs. Account Membership Roles
- **Global Roles (`User.role`):**
  - `ADMIN`: Administrative oversight (creating accounts, freezing/closing accounts, managing users, viewing global audit logs). Account operations still require explicit membership or controlled administrator mechanisms.
  - `HOLDER`: Customer principals restricted exclusively to accounts for which they possess an active `AccountMembership`.
  - `AUDITOR`: Regulatory and compliance principals. Strictly read-only across all system and account contexts.
- **Account Membership Roles (`AccountMembership.membership_role`):**
  - `OWNER`: Full permitted account management (read, financial operations, membership delegation, account metadata updates).
  - `OPERATOR`: Operational execution (read, initiate financial operations); strictly prohibited from membership management or account updates.
  - `VIEWER`: Read-only access to account balance, details, ledger entries, and transaction history. Prohibited from mutating operations.

#### B. Permission Matrix & Enforcement Hierarchy

| Action | Required Global Role | Minimum Membership Role | AUDITOR Permitted? |
| :--- | :--- | :--- | :--- |
| **`AccountAction.READ`** | `ADMIN`, `HOLDER`, `AUDITOR` | `VIEWER` | ✅ Yes (Read-Only) |
| **`AccountAction.OPERATE`** | `ADMIN`, `HOLDER` | `OPERATOR` | ❌ No (`AuditorReadOnlyViolationError` -> 403) |
| **`AccountAction.MANAGE_MEMBERS`**| `ADMIN`, `HOLDER` | `OWNER` | ❌ No (`AuditorReadOnlyViolationError` -> 403) |
| **`AccountAction.UPDATE_DETAILS`** | `ADMIN`, `HOLDER` | `OWNER` | ❌ No (`AuditorReadOnlyViolationError` -> 403) |
| **`SystemAction.CREATE_ACCOUNT`** | `ADMIN` | N/A (System) | ❌ No |
| **`SystemAction.CHANGE_ACCOUNT_STATUS`** | `ADMIN` | N/A (System) | ❌ No |
| **`SystemAction.VIEW_ALL_ACCOUNTS`** | `ADMIN` | N/A (System) | ❌ No |
| **`SystemAction.VIEW_AUDIT_LOG`** | `ADMIN`, `AUDITOR` | N/A (System) | ✅ Yes (Read-Only) |
| **`SystemAction.MANAGE_USERS`** | `ADMIN` | N/A (System) | ❌ No |

#### C. Conflict Resolution: Global AUDITOR Read-Only Invariant
To prevent privilege escalation where a database membership record might grant `OWNER` or `OPERATOR` status to an auditor, `check_account_permission` enforces that if `user.role == UserRole.AUDITOR`, any write action (`OPERATE`, `MANAGE_MEMBERS`, `UPDATE_DETAILS`) raises `AuditorReadOnlyViolationError` (HTTP 403). Global read-only auditor policy strictly supersedes account membership roles.

#### D. Anti-IDOR / Anti-BOLA Defense (Account Existence Anti-Enumeration)
- When a user requests access to an account UUID where they hold no active `AccountMembership`, the authorization service raises `AccountNotFoundError` (HTTP 404 Not Found), returning `{"detail": "Account not found"}`.
- Because non-existent account UUIDs and unowned account UUIDs produce identical HTTP 404 responses, malicious actors cannot enumerate or discover valid customer account IDs via UUID guessing or parameter tampering.
- Authenticated account members attempting actions beyond their membership role receive HTTP 403 Forbidden (`{"detail": "Insufficient permissions for this account action"}`).

#### E. Account Status Constraints
- Financial operations (`AccountAction.OPERATE`) enforce that `account.status == AccountStatus.ACTIVE`.
- Accounts in `FROZEN` or `CLOSED` state reject mutating operations with `AccountStatusError` (HTTP 403).
- Read access (`AccountAction.READ`) remains accessible to members on frozen or closed accounts for auditability.

#### F. Administrative Account Registry & Safe Demo Provisioning Threat Model
- **Administrative Registry Authorization (`GET /admin/accounts`):**
  - Restricted strictly to `UserRole.ADMIN` principals via system action `SystemAction.VIEW_ALL_ACCOUNTS` and dependency `require_admin`.
  - Non-admin callers (`HOLDER`, `AUDITOR`) receive HTTP 403 Forbidden (`{"detail": "Insufficient role permissions"}`).
  - Unauthenticated callers receive HTTP 401 Unauthorized (`{"detail": "Authentication required"}`).
- **Principle of Least Privilege & Separation of Duties:**
  - Administrative registry visibility provides system oversight into customer accounts and their lifecycle status (`ACTIVE`, `FROZEN`, `CLOSED`).
  - Registry visibility deliberately does **NOT** grant operational execution rights (`AccountAction.OPERATE`, e.g., deposit, withdrawal, transfer) or private account statement inspection.
  - An Admin attempting financial transactions against customer accounts without holding explicit operational membership is rejected (HTTP 404 anti-IDOR protection for non-members, or HTTP 403 Forbidden for non-operators).
- **System Clearing Account Isolation:**
  - The internal system clearing vault (`SYSTEM_CLEARING`) is strictly excluded from `GET /admin/accounts` results (`Account.account_number != SYSTEM_CLEARING_ACCOUNT_NUMBER`), preventing internal clearing infrastructure from being exposed or treated as an ordinary customer account.
- **Safe Demo Provisioning & Evaluation Credentials:**
  - `backend/app/scripts/seed_demo.py` is an idempotent provisioning script intended strictly for local development and assessment evaluation.
  - Passwords are never stored in plaintext and are hashed using RFC 9106 Argon2id parameters before insertion.
  - Existing user credentials and roles are never overwritten or modified if they already exist.
  - Sample customer accounts provisioned for the demo holder are initialized with 0 starting balance, preserving double-entry mathematical balance invariants without fabricating unjournaled money.
  - Demo quick-login buttons on the frontend `LoginPage` are strictly guarded by development mode (`import.meta.env.DEV`) or an explicit environment flag (`VITE_ENABLE_DEMO_CREDENTIALS === 'true'`), preventing automated exposure in production client bundles.

#### G. Server-Enforced Decisions & Immutability
- Role and membership data are queried exclusively server-side from PostgreSQL/database models. Client-supplied role attributes are strictly ignored.
- Rejected authorization requests execute zero database mutations, preserving ledger and account integrity.

#### H. Limitations & Residual Risks
- System-wide account creation and status change endpoints remain restricted to `ADMIN`.
- Row-Level Security (RLS) is enforced at the application/ORM service layer. Multi-tenant database-level RLS policies in PostgreSQL are deferred.

### 11. Financial Transactions, Double-Entry Invariants, Concurrency & Idempotency Threats

#### A. Double-Spend & Concurrency Race Condition Threats
- **Threat:** An attacker or high-frequency client initiates two concurrent withdrawal or transfer requests of ₹700 from an account holding only ₹1,000. Without serialization, both requests could read the pre-transaction balance of ₹1,000 simultaneously, both determine funds are sufficient, and both execute debits, resulting in an illicit balance of -₹400 (lost update / double-spend).
- **Mitigation:**
  - **Pessimistic Row-Level Locking:** Accounts are locked using `SELECT ... FOR UPDATE` with `execution_options(populate_existing=True)`.
  - **Deterministic Lock Ordering:** In multi-account operations (transfers), accounts are locked in strictly sorted UUID order (`min(id1, id2)`, then `max(id1, id2)`), eliminating circular wait conditions and database deadlocks.
  - **Re-check Under Exclusive Lock:** The account balance and active status are re-verified strictly under the acquired row lock.
  - **Read Committed Serialization:** In PostgreSQL, the second transaction waits until the first commits, then receives the updated row with the freshly decremented balance, detects `balance < amount_paise`, and raises `InsufficientFundsError`.
  - **Database Check Constraint:** As defense-in-depth, `ck_accounts_balance_non_negative` (`balance >= 0 OR account_number = 'SYSTEM_CLEARING'`) physically rejects any database update that would cause a customer account balance to drop below zero, while permitting the system clearing account to reflect debit rail claims.

#### B. Network Replay & Idempotency Threats
- **Threat:** Transient network disconnects, timeouts, or impatient user double-clicks cause the same transaction payload to be submitted multiple times, risking duplicate money movement. Alternatively, an attacker attempts to reuse an existing idempotency key with modified financial amounts (parameter tampering).
- **Mitigation:**
  - **User-Scoped Idempotency Table:** `idempotency_records` table with a composite unique constraint `(user_id, idempotency_key)`.
  - **Canonical Request Hashing:** Standard SHA-256 digest computed across canonical sorted JSON keys (`compute_request_hash`).
  - **Reservation & In-Flight Detection:** The key is reserved atomically during the initial transaction step. If another request attempts to use the same key while execution is ongoing, `IdempotencyInFlightError` (HTTP 409) is raised.
  - **Parameter Tampering Detection:** If a completed record exists but the new request hash does not match, `IdempotencyCollisionError` (HTTP 409) is raised.
  - **Expiration & Safe Reclaiming:** Enforces UTC key expiration (`expires_at <= now`). Expired completed or abandoned in-flight records are safely reclaimed in-place without key collisions or ghost locks (IDEMP-001).
  - **Pessimistic Row Locking on Lookup (`with_for_update`):** Initial idempotency lookup enforces row-level locking via `SELECT ... FOR UPDATE`, guaranteeing that concurrent workers competing for an expired reservation execute deterministically under PostgreSQL READ COMMITTED isolation. Exactly one worker reclaims and executes, while competing workers block, evaluate the fresh committed state upon unblocking, and safely receive cached replay or collision error.
  - **Safe Replay:** When a matching completed record exists and is unexpired, the original HTTP status code and response payload are returned directly from the database cache without mutating account balances or creating duplicate ledger entries.

#### C. Floating-Point & Monetary Type Coercion Threats
- **Threat:** Financial calculations using IEEE-754 floating-point numbers introduce fractional rounding errors. Type coercion of booleans (`True` -> `1`) or strings in JSON payloads can bypass intended business logic or cause database integer overflow crashes (VAL-001, VAL-002).
- **Mitigation:**
  - Floating-point arithmetic is strictly forbidden across the codebase.
  - All monetary values are represented as minor unit integers (paise) stored in 64-bit `BigInteger` database columns and typed as `int` in Python.
  - Pydantic request validators enforce `strict=True`, `gt=0`, and `le=9_223_372_036_854_775_807` (signed 64-bit BigInt max), rejecting booleans, floats, strings, and overflow values with HTTP 422 before reaching the database.

#### D. Unbalanced Ledger & Counterparty Imbalance Threats
- **Threat:** An operational bug or partial failure posts an isolated debit without a corresponding credit, violating double-entry balance and corrupting system accounting. Alternatively, an arbitrary unjournaled opening balance creates unbacked money (FIN-001).
- **Mitigation:**
  - **Atomic Unit of Work:** The transaction header, debit entry, credit entry, balance updates, and idempotency record are flushed and committed in a single atomic database transaction. Any exception triggers a full `db.rollback()`.
  - **Mathematical Invariant Verification:** `post_ledger_transaction` explicitly verifies that $\sum \text{Debits} == \sum \text{Credits}$. Any discrepancy raises `UnbalancedLedgerError` before persisting.
  - **System Clearing Account (Zero-Balance Foundation):** For external money injections (deposits) and removals (withdrawals), the balanced counterpart entry is posted against `SYSTEM_CLEARING`. Starting at 0 balance, it reconciles to 0 opening balance with its ledger journals. System-wide money conservation is exact: $\sum \text{Customer Balances} + \text{Clearing Balance} == 0$.
  - **Auditing & Reconciliation:** `reconcile_account_balance` recalculates net ledger entries ($\sum \text{Credits} - \sum \text{Debits}$) and compares against the cached balance snapshot, reporting discrepancies (`is_reconciled=True`).
  - **Clearing Account Protections:**
    - Administrative status changes (`FROZEN`, `CLOSED`) on `SYSTEM_CLEARING` are prohibited (`AccountStatusError`, HTTP 403) (SEC-002).
    - Peer-to-peer transfers targeting or sourcing `SYSTEM_CLEARING` are prohibited (`ClearingAccountTransferError`, HTTP 400) (FIN-002).
    - Concurrency-safe initialization: `get_or_create_system_clearing_account` uses nested transaction savepoints (`begin_nested()`) to catch `IntegrityError` without session abort (CONC-001).

#### E. Transaction Authorization & Anti-IDOR Defense
- **Threat:** Malicious users attempt to inspect transactions of other accounts (BOLA/IDOR) or administrative users bypass account membership to view financial histories (AUTH-001, SEC-001).
- **Mitigation:**
  - `get_transaction_by_id` strictly requires active membership on at least one involved account (source or destination). Non-members (including `ADMIN` and `AUDITOR` without membership) receive HTTP 404 (`Transaction not found`), preventing existence disclosure per PROMPT-030 policy.
  - Role comparison safely handles both `UserRole` enums and raw database string values, avoiding crashes on valid string roles.
  - Inactive users are rejected immediately with HTTP 403.

#### E. Audit Logging & Non-Repudiation
- **Threat:** Malicious actors attempt unauthorized financial transfers or status alterations and deny involvement.
- **Mitigation:**
  - Every financial transaction (`TRANSACTION_DEPOSIT`, `TRANSACTION_WITHDRAWAL`, `TRANSACTION_TRANSFER`) and account lifecycle status change (`ACCOUNT_STATUS_CHANGE`) emits an immutable `AuditEvent` recording actor user UUID, client IP address, action kind, and target entities.
  - Audit events are enrolled in the active database transaction, ensuring audit logs are written if and only if the business transaction succeeds. Sensitive credential parameters are scrubbed before storage.

#### F. Frontend Client & Session Storage Threats
- **Threat:** Client-side XSS attacks steal session tokens from browser storage (`localStorage` or `sessionStorage`), or cross-site request forgery triggers unauthorized financial transactions. Duplicate user clicks or ambiguous network timeouts cause duplicate money movement.
- **Mitigation:**
  - **Zero Browser Storage of Session Tokens:** Authentication tokens are stored exclusively in HTTP-only, `SameSite=Lax` browser cookies managed by the server. No session token or password hash is ever placed in `localStorage`, `sessionStorage`, or JavaScript-accessible variables.
  - **CSRF Defense:** Browser automatically attaches `Origin` headers which are validated by the backend's strict origin normalization middleware against `settings.cors_origins_list`.
  - **Client-Side Idempotency Key Management:** Every user-initiated operation generates a cryptographic UUID (`crypto.randomUUID()`) as `Idempotency-Key`. The key is held in component state and reused across retries on transient network errors, preventing duplicate financial execution while ensuring safe response replays.
  - **In-Flight Double-Click Prevention:** Form submit actions immediately set `isSubmitting=true` and disable UI buttons until the backend responds.
  - **Backend as Authoritative Source of Truth:** The frontend performs zero authoritative balance calculations. Balances, transaction statuses, and chronological statements are rendered exclusively from authenticated backend ledger responses.

#### G. Database Ledger Immutability, Privilege Separation & Fail-Closed Runtime Threats
- **Threat:** An attacker who gains SQL injection, an insider with database access, or a compromised application query attempts to execute `UPDATE`, `DELETE`, or `TRUNCATE` against historical ledger entries to alter balance records, conceal embezzlement, or forge transactions.
- **Threat:** Using a custom session parameter (e.g. `SET ledgerline.allow_ledger_maintenance = 'true'`) as a trigger bypass provides no security boundary because any SQL execution path can set session variables.
- **Threat:** Running application connections under a table-owner or superuser role allows attackers to drop triggers, alter schema definitions, disable immutability guards, or grant themselves elevated privileges.
- **Threat:** Silent fallback to privileged connection URLs or misconfigured runtime database URLs leaves the application operating under administrative database privileges.
- **Threat:** Deploying to production with unrestricted database connectivity allows accidental or malicious connection to unauthorized hosts, rogue databases, or test databases containing simulated financial data.
- **Threat:** Routine schema migrations requiring cluster superuser privileges create operational vulnerabilities where migrations can alter cluster-wide configurations, create arbitrary superusers, or access out-of-scope system catalogs.
- **Mitigation:**
  - **Row-Level Immutability Trigger (`trg_ledger_entries_immutability`):** Executes `protect_ledger_entries_immutability()` `BEFORE UPDATE OR DELETE ON ledger_entries FOR EACH ROW`, raising an exception with SQLSTATE `20000` on any UPDATE or DELETE attempt.
  - **Statement-Level Truncate Protection (`trg_ledger_entries_truncate`):** Executes `protect_ledger_entries_truncate()` `BEFORE TRUNCATE ON ledger_entries FOR EACH STATEMENT`, raising an exception with SQLSTATE `20000`.
  - **Zero Session-Variable Bypass:** No maintenance bypass is provided in the trigger functions. All modifications and deletions are unconditionally rejected.
  - **Three-Tier Database Role Separation:**
    - **Bootstrap Administrator (`ledgerline`):** Dedicated cluster administrator (`POSTGRES_USER`). Used exclusively for initial container provisioning and database creation. Never used for application runtime or routine migrations.
    - **Migration / Schema-Owner Role (`ledgerline_migrator`):** Dedicated least-privilege migration role (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`). Owns the `public` schema and all domain tables/functions. Routine Alembic migrations execute under `ledgerline_migrator` via `MIGRATION_DATABASE_URL` without superuser privileges. Cannot create superusers or alter other roles (rejected with SQLSTATE `42501`).
    - **Application Runtime Role (`ledgerline_app`):** Dedicated non-superuser role (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`). Holds zero DDL, zero superuser, and zero maintenance privileges.
  - **Least Privilege Table Grants & Default Privileges:** `ledgerline_app` possesses strictly `SELECT, INSERT` on `ledger_entries` and `audit_events` (zero UPDATE, DELETE, or TRUNCATE). `scripts/init_db.sql` configures default privileges for `ledgerline_migrator`, and migration `c18f3a8b9e10` explicitly executes `REVOKE UPDATE, DELETE, TRUNCATE` on immutable tables to enforce least privilege.
  - **Table Ownership Boundary:** `ledgerline_app` does not own `ledger_entries` or any other domain table. PostgreSQL rejects `ALTER TABLE ... DISABLE TRIGGER`, `DROP TRIGGER`, and `ALTER TABLE ... OWNER TO` with SQLSTATE `42501` (`must be owner of table ledger_entries`).
  - **Environment-Aware Fail-Closed Database URL Validation:**
    - In local development and test environments, `validate_runtime_database_url` strictly confines connections to local loopback hosts (`localhost`, `127.0.0.1`, `::1`), port 5432, and approved databases (`ledgerline`, `ledgerline_test`).
    - In production environments, `validate_runtime_database_url` requires explicit, non-empty allowlists via `DB_ALLOWED_HOSTS` and `DB_ALLOWED_DATABASES`. If either allowlist is missing or empty, startup fails closed immediately (zero unrestricted access).
    - In production, test database targets (`ledgerline_test`, `*_test`, `test_*`) and SQLite engines are strictly rejected.
    - Across all environments, `APPROVED_RUNTIME_ROLE = "ledgerline_app"` is enforced, and privileged roles (`PROHIBITED_RUNTIME_ROLES = frozenset({"ledgerline", "ledgerline_migrator", "postgres", "root", "admin"})`) are unconditionally rejected.
  - **Zero Fallback:** `create_app_engine()` strictly requires an approved runtime database URL. If missing or invalid, engine creation raises `ValueError` immediately rather than falling back to privileged migration settings.
  - **Isolated Test-Administration Maintenance Mechanism:** Integration test fixtures are cleaned up using the isolated test database schema-owner connection (`ledgerline_migrator`), which holds table-owner privileges to disable the trigger temporarily during test teardown and re-enables it in a `finally` block. Runtime application connections cannot execute this teardown mechanism.

#### H. Database Timestamp Consistency, Temporal Tampering & Stale Metadata Threats
- **Threat:** Operational modifications performed via direct SQL (administrative scripts, bulk data migrations, or raw SQL queries) bypass client-side and ORM `onupdate` hooks, leaving `updated_at` timestamps stale and undermining temporal audits, cache invalidation, and replication tracking.
- **Threat:** An attacker or malicious client attempts to backdate accounts or transactions by supplying a forged `created_at` or `updated_at` value in an UPDATE payload.
- **Threat:** Spurious timestamp increments on no-op updates (where no row attributes actually changed) corrupt change-data-capture pipelines and audit logs with false change events.
- **Mitigation:**
  - **Server-Side Timestamp Trigger (`update_updated_at_column`):** Attached `BEFORE UPDATE` to all mutable entities (`accounts`, `users`, `transactions`). Automatically evaluates `NEW.updated_at = clock_timestamp()` directly inside PostgreSQL, guaranteeing fresh timestamps on both ORM and raw SQL updates.
  - **`created_at` Immutability Protection:** Enforces `NEW.created_at = OLD.created_at`, physically blocking any attempt to modify or backdate creation timestamps on existing records.
  - **No-Op Update Suppression:** Evaluates `IF (NEW IS NOT DISTINCT FROM OLD) THEN RETURN OLD; END IF;`, ensuring that updates leaving all column values identical do not modify `updated_at`.
  - **Client Forgery Override:** Any client-supplied `updated_at` value in an UPDATE statement is unconditionally overwritten with PostgreSQL's authoritative `clock_timestamp()`.
  - **Table Ownership Security:** The trigger function and table triggers are owned by `ledgerline_migrator`. The runtime application role `ledgerline_app` is denied table-owner privileges and cannot disable, drop, or alter timestamp triggers (SQLSTATE `42501`).
  - **Immutable Table Exclusion:** Immutable tables (`ledger_entries`, `audit_events`) are strictly excluded from update triggers to preserve their append-only double-entry integrity.

## Trust Boundaries

LedgerLine establishes four primary trust boundaries separating external untrusted actors, proxy layers, backend processing services, and internal data persistence tiers:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        UNTRUSTED EXTERNAL CLIENT                       │
│             (Web Browsers, Automated Attackers, Mobile Clients)         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                         [ TRUST BOUNDARY 1 ]
                      Reverse Proxy & TLS Ingress
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       REVERSE PROXY TIER (Nginx)                       │
│  - Static Asset Delivery                                               │
│  - Port 3000 published to host; internal proxy-net (172.28.1.10)       │
│  - Appends X-Forwarded-For, X-Forwarded-Proto, X-Forwarded-Host        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                         [ TRUST BOUNDARY 2 ]
                 Proxy-to-Backend Network Boundary
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      APPLICATION TIER (FastAPI)                        │
│  - Internal port 8000 (NOT published to host)                          │
│  - FORWARDED_ALLOW_IPS: "127.0.0.1,172.28.1.10" (Nginx trust only)    │
│  - CSRF Protect Middleware (Allowed Origins whitelist)                │
│  - Rate Limiting (slowapi: 5/min register, 10/min login)               │
│  - Strict Payload Hardening (Pydantic extra='forbid')                  │
│  - Cookie Session Resolution (Argon2id, SHA-256 session token hash)    │
│  - Route-by-Route RBAC & Anti-IDOR Authorization Service              │
│  - Double-Entry Balance Invariant & Deterministic Lock Manager         │
│  - Recursive Credential Scrubbing Audit Engine                         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                         [ TRUST BOUNDARY 3 ]
              Application-to-Database Network Boundary
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    DATABASE PERSISTENCE (PostgreSQL)                   │
│  - Internal db-net (Port 5432 NOT published in default/staging)        │
│  - Non-superuser runtime role: ledgerline_app (least privilege)        │
│  - Migrations run as: ledgerline_migrator (schema owner, non-superuser) │
│  - Physical Check Constraints (ck_accounts_balance_non_negative)       │
│  - Row-Level Immutability Trigger (protect_ledger_entries_immutability)│
│  - Statement Truncate Trigger (protect_ledger_entries_truncate)        │
│  - Updated-At Timestamp Triggers with Clock Timestamp & No-Op Filter   │
│  - REVOKE UPDATE, DELETE, TRUNCATE on ledger_entries and audit_events  │
└────────────────────────────────────────────────────────────────────────┘

                         [ TRUST BOUNDARY 4 ]
           Identity Assertion & Row-Level Security Boundary
  - Database Row-Level Security (RLS) is currently DISABLED.
  - Custom PostgreSQL session GUCs are NOT trusted identity mechanisms.
  - Authorization is verified strictly in the FastAPI application layer.
```

### Trust Boundary Analysis

1. **Boundary 1: External Client <-> Reverse Proxy (Nginx Ingress)**
   - Untrusted clients interact with the published Nginx port (port 3000 in staging).
   - Nginx handles static file delivery, routes API requests to backend, and enforces header sanitization.
   - Client browsers are fundamentally untrusted execution environments; no sensitive secrets or authoritative calculations are placed on the client.

2. **Boundary 2: Reverse Proxy (Nginx) <-> Backend API (FastAPI / Uvicorn)**
   - Communicates across the internal Docker bridge network `proxy-net`.
   - Backend trusts forwarded headers (`X-Forwarded-For`, `X-Forwarded-Proto`) strictly from `127.0.0.1` and `172.28.1.10` (the guaranteed static IP of Nginx). Wildcard CIDR ranges (`172.16.0.0/12`) are explicitly prohibited.
   - All state-changing requests must pass strict canonical origin verification (`CSRFProtectMiddleware`).
   - All request bodies are strictly filtered against Pydantic models with `model_config = ConfigDict(extra="forbid")`.

3. **Boundary 3: Backend Application Service <-> PostgreSQL Database**
   - Communicates across the isolated internal Docker bridge network `db-net`.
   - The database port `5432` has zero host port publishing in staging/production (`docker-compose.yml`). Host access is available strictly through a developer override (`docker-compose.dev.yml`) binding exclusively to `127.0.0.1`.
   - Application connects strictly as `ledgerline_app`, possessing zero DDL, zero superuser, and zero update/delete permissions on ledger journals and audit records.
   - Database check constraints and triggers enforce financial integrity even if application logic were corrupted.

4. **Boundary 4: Identity & Authorization Boundary (Application vs Database Layer)**
   - All role-based access control (ADMIN, HOLDER, AUDITOR), account-level permissions (OWNER, OPERATOR, VIEWER), and anti-IDOR checks are evaluated and enforced exclusively within the FastAPI application layer.
   - Database-level Row-Level Security (RLS) is currently **DISABLED**.
   - PostgreSQL custom session settings / GUCs (`app.current_user_id`, `pg_temp._active_context`) are recognized as vulnerable to transaction reuse, connection pooling replay, and unprivileged GUC tampering, and are **NOT** utilized as trusted security boundaries.

---

## Threat Actors

| Threat Actor | Description & Motivation | Capabilities & Access Level |
| :--- | :--- | :--- |
| **External Unauthenticated Attacker** | Internet scanners, script kiddies, and credential stuffers seeking unauthorized access, information leaks, or service disruption. | Unauthenticated HTTP/HTTPS access to public ingress. Can forge request headers, guess URLs, replay requests, and attempt brute-force login/registration. |
| **Malicious Authenticated Customer (`HOLDER`)** | Legitimate system user attempting to access other users' accounts, steal funds, or escalate administrative privileges. | Valid session cookie as `UserRole.HOLDER`. Can invoke authenticated endpoints. Attempts IDOR/BOLA by supplying other customers' UUIDs, concurrent race condition requests, or mass assignment payloads. |
| **Compromised / Rogue Auditor (`AUDITOR`)** | Regulatory compliance user attempting to execute financial transactions or alter account data under the guise of audit authority. | Valid session cookie as `UserRole.AUDITOR`. Authorized to read audit logs and inspect accounts. Attempts write actions (`deposit`, `withdraw`, `transfer`, `patch`) or membership elevation. |
| **Rogue Account Member (`VIEWER` / `OPERATOR`)** | User granted limited delegate access to an account who attempts operations exceeding their assigned role. | Valid membership on a specific account as `VIEWER` or `OPERATOR`. Attempts unauthorized withdrawals (`VIEWER`) or account renaming/delegation (`OPERATOR`). |
| **Database Network Intruder / SQL Adversary** | Adversary who gains network access to PostgreSQL or achieves partial SQL query injection. | Direct SQL execution capability under the `ledgerline_app` runtime database role. Attempts `UPDATE`, `DELETE`, or `TRUNCATE` against ledger history or audit logs. |

---

## Threat Register

| ID | Threat & Attack Scenario | Primary Impact | Existing Mitigation & Security Controls | Automated Test Verification | Residual Risk |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **THR-01** | **BOLA / IDOR on Account Details, Metadata & Statements:** Authenticated attacker replaces their account UUID with victim's UUID in `GET /accounts/{id}`, `PATCH /accounts/{id}`, or `GET /accounts/{id}/statement`. | Confidentiality & Integrity breach; unauthorized account inspection or tampering. | `get_account_for_user()` requires active membership. Unauthorized lookups raise `AccountNotFoundError` (HTTP 404 anti-enumeration). | `tests/security/test_idor_bola.py::test_idor_prevented_on_get_account_detail`<br>`tests/security/test_idor_bola.py::test_idor_prevented_on_patch_account_metadata`<br>`tests/security/test_idor_bola.py::test_idor_prevented_on_get_statement` | Application-level check; RLS disabled at database tier. |
| **THR-02** | **BOLA / IDOR on Financial Operations:** Attacker submits `POST /transactions/deposit`, `withdraw`, or `transfer` targeting an unowned victim account. | Theft of funds; unauthorized debit or credit. | `execute_deposit`, `execute_withdrawal`, and `execute_transfer` enforce `AccountAction.OPERATE` membership via `get_account_for_user`. Rejects unowned accounts with HTTP 404. | `tests/security/test_idor_bola.py::test_idor_prevented_on_deposit_to_unowned_account`<br>`tests/security/test_idor_bola.py::test_idor_prevented_on_withdraw_from_unowned_account`<br>`tests/security/test_idor_bola.py::test_idor_prevented_on_transfer_from_unowned_source_account` | Requires active application runtime enforcement. |
| **THR-03** | **BOLA / IDOR on Transaction Inspection:** Attacker attempts `GET /transactions/{id}` for a peer-to-peer transaction between third parties. | Privacy leak of financial counterparty details and amounts. | `get_transaction_by_id` checks active membership in at least one involved account. Non-members receive HTTP 404. | `tests/security/test_idor_bola.py::test_idor_prevented_on_get_transaction_by_unrelated_user`<br>`tests/security/test_idor_bola.py::test_idor_prevented_on_peer_transfer_for_third_party` | None; verified anti-enumeration. |
| **THR-04** | **Privilege Escalation to Admin Endpoints:** Ordinary `HOLDER` or `AUDITOR` attempts `POST /accounts`, `POST /accounts/{id}/status`, or `GET /admin/accounts`. | Unauthorized account creation, account freezing, or system registry enumeration. | `require_admin` dependency enforces `UserRole.ADMIN`. Rejects non-admin users with HTTP 403 Forbidden. DB state remains untouched. | `tests/security/test_role_enforcement_and_escalation.py::TestGlobalAdminRoleEnforcement` | None. |
| **THR-05** | **Auditor Write Action Violation & Escalation:** `AUDITOR` attempts `deposit`, `withdraw`, `transfer`, or `PATCH /accounts/{id}`. Even if an auditor holds `OWNER` membership in DB, write actions must be blocked. | Unauthorized ledger mutations by compliance personnel. | `check_account_permission` enforces that if `user.role == UserRole.AUDITOR`, all `WRITE_ACCOUNT_ACTIONS` raise `AuditorReadOnlyViolationError` (HTTP 403). Global auditor policy strictly overrides membership role. | `tests/security/test_role_enforcement_and_escalation.py::TestAuditorReadOnlyRestrictions` | None. Global read-only constraint verified. |
| **THR-06** | **Account Membership Role Violation:** `VIEWER` member attempts operational mutation (`deposit`, `withdraw`, `transfer`), or `OPERATOR` attempts `PATCH /accounts/{id}`. | Unauthorized money movement or account metadata modification. | Granular role hierarchy: `OPERATE` requires `OPERATOR`; `UPDATE_DETAILS` and `MANAGE_MEMBERS` require `OWNER`. Violations raise HTTP 403. | `tests/security/test_role_enforcement_and_escalation.py::TestAccountMembershipRoleEnforcement` | None. |
| **THR-07** | **Mass Assignment & Parameter Injection:** Attacker injects extra fields (e.g. `role='ADMIN'`, `balance=999999`, `is_active=False`, `status='ACTIVE'`) into registration, account creation, patch, or transaction payloads. | Privilege escalation or arbitrary balance modification. | All Pydantic request models configure `model_config = ConfigDict(extra="forbid")`. Unapproved fields trigger HTTP 422 immediately before service execution. | `tests/security/test_mass_assignment_and_payload_hardening.py` | None. |
| **THR-08** | **Session Hijacking, Replay & Inactive User Exploitation:** Use of missing, malformed, expired, or revoked sessions, or access by deactivated users (`is_active=False`). | Unauthorized session takeover or continued access by terminated employees. | `validate_session` verifies SHA-256 token hash, unexpired UTC timestamps, unrevoked status, and `is_active=True`. Fails closed with HTTP 401 or HTTP 403. | `tests/security/test_session_and_inactive_users.py::TestSessionValidationAndLifecycle`<br>`tests/security/test_session_and_inactive_users.py::TestInactiveUserRejection` | In-memory session tracking not used; relies on DB lookup. |
| **THR-09** | **Revoked Membership Continued Access:** User whose account membership row was deleted attempts continued operations or data retrieval. | Unauthorized post-revocation access to account. | Dynamic per-request membership lookup raises `AccountNotFoundError` (HTTP 404 anti-IDOR). | `tests/security/test_session_and_inactive_users.py::TestRevokedMembershipBehavior` | None. |
| **THR-10** | **Sensitive Credential Exposure in Audit Trail:** Plaintext passwords, tokens, API keys, or session secrets logged to `audit_events.event_metadata`. | Credential exfiltration via audit logs or administrative consoles. | `record_audit_event` recursively sanitizes metadata against `forbidden_keys` (`password`, `token`, `raw_token`, `password_hash`, `token_hash`, `secret`, `session_secret`, `api_key`, `credentials`). | `tests/security/test_audit_and_immutability_security.py::TestCredentialScrubbingInAuditTrail` | None. |
| **THR-11** | **Concurrent Double-Spend Race Condition:** Concurrent withdrawal/transfer requests read positive balance simultaneously, causing negative account balance. | Ledger corruption; unbacked money extraction. | Pessimistic row-level locking (`SELECT ... FOR UPDATE` with sorted UUID lock ordering), re-check under lock, and PostgreSQL `ck_accounts_balance_non_negative` constraint. | `tests/integration/test_concurrency_postgres.py` | None. Race conditions serialized by database row locks. |
| **THR-12** | **Duplicate Request Replay / Timeout Retry:** Network retry causes duplicate deposit, withdrawal, or transfer execution. | Duplicate money movement. | `idempotency_records` table with composite key `(user_id, idempotency_key)`, canonical payload SHA-256 hashing, atomic reservation, and cached response replay. | `tests/unit/test_transaction_service.py` | Idempotency keys expire after 24h. |
| **THR-13** | **Direct SQL Ledger & Audit Log Tampering:** Adversary with SQL access under application role attempts `UPDATE`, `DELETE`, or `TRUNCATE` against `ledger_entries` or `audit_events`. | History tampering; concealment of embezzlement. | PostgreSQL triggers `trg_ledger_entries_immutability` and `trg_ledger_entries_truncate` raise SQLSTATE `20000`. Table grants explicitly revoke `UPDATE, DELETE, TRUNCATE` from `ledgerline_app`. | `tests/integration/test_ledger_immutability_postgres.py` | Table owner (`ledgerline_migrator`) can alter triggers during maintenance. |
| **THR-14** | **Database Timestamp Backdating & Forgery:** Adversary attempts to backdate records by forging `created_at` or `updated_at` in SQL queries. | Tampered audit timelines. | Server-side trigger `update_updated_at_column` enforces `NEW.updated_at = clock_timestamp()` and `NEW.created_at = OLD.created_at` with no-op update suppression. | `tests/integration/test_timestamp_consistency_postgres.py` | None. |
| **THR-15** | **Cross-Site Request Forgery (CSRF):** Malicious site triggers state-changing actions via user's ambient session cookies. | Unauthorized financial operations executed in victim's browser context. | `CSRFProtectMiddleware` strictly validates canonical `Origin` and `Referer` against configured `cors_origins_list`. Cookies configure `SameSite=Lax`. | `tests/unit/test_csrf.py` | Non-browser clients must pass valid Origin/Referer header. |
| **THR-16** | **Staging Network Exposure & Trusted Proxy Spoofing:** Attacker probes exposed database ports or spoofs `X-Forwarded-For` to bypass IP controls. | Database breach; IP spoofing in audit logs. | `docker-compose.yml` removes database host port publishing entirely. Uvicorn configured with `FORWARDED_ALLOW_IPS: "127.0.0.1,172.28.1.10"` (guaranteed static IP of Nginx). | Verified via containerization inspection and `docker-compose.yml`. | None on internal bridge networks. |

---

## Residual Risks

The following residual risks are explicitly recognized and documented:

1. **Database Row-Level Security (RLS) is Disabled:**
   - PostgreSQL Row-Level Security is currently **NOT enabled** on domain tables.
   - All tenant isolation, BOLA/IDOR protection, and role-based permissions are enforced strictly in the FastAPI application and ORM service layer.
   - If an attacker obtains direct arbitrary SQL execution access to the database under the `ledgerline_app` user, the database will not restrict `SELECT` queries across customer accounts.

2. **Custom PostgreSQL GUC Session Identity is Untrusted:**
   - Proposed mechanisms utilizing session-level GUCs (e.g. `SET LOCAL app.current_user_id = ...` or `pg_temp._active_context`) are **NOT trusted** as a security boundary.
   - Because connection poolers (PgBouncer, SQLAlchemy connection pooling) reuse physical connections, and unprivileged SQL callers can issue `SET` statements or alter session variables, custom GUC claims cannot establish a tamper-proof cryptographic identity boundary without secure hardware or signed assertion protocols.
   - Application-layer authentication and transaction isolation remain the primary authoritative boundary.

3. **In-Memory Rate Limiting Scope:**
   - Public endpoint rate limiting via `slowapi` maintains counters in process-local memory.
   - In horizontally scaled deployments with multiple container replicas or Uvicorn worker processes, rate limits are not shared across workers without a centralized Redis cache.

4. **Fixed Session Expiry:**
   - User sessions utilize a fixed 24-hour expiration window. Sliding window session extension has not been implemented.

5. **Single-Node Infrastructure:**
   - The current staging deployment is containerized on a single Docker host. Multi-region database replication, automated cluster failover, and hardware security modules (HSM) for cryptographic keys remain future architectural enhancements.
