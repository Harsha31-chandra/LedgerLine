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

## Trust Boundaries

*To be documented as implementation progresses.*

## Threat Actors

*To be documented as implementation progresses.*

## Threat Register

*To be populated with specific threats, attack paths, mitigations, test IDs and residual risks.*

## Residual Risks

*To be stated honestly for threats not fully mitigated.*
