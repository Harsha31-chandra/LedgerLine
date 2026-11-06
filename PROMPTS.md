# PROMPTS.md — AI Usage Log

> This document records every meaningful AI-assisted task during the development of LedgerLine.
> In accordance with the project requirements:
> - Complete original prompt text is preserved exactly as submitted without shortening or paraphrasing.
> - Sequential IDs are maintained.
> - Actual outputs, files changed, human verification, genuine AI mistakes, human corrections, and verified tests/commits are documented honestly without fabrication.

---

## Entry 1 — 2026-11-06

**Sequential ID:** PROMPT-001

**Task:** Initial repository inspection, architectural proposal, dependency selection, and project structure planning.

**Tool:** Antigravity AI

**Exact Submitted Prompt Text:**
```text
I am building LedgerLine, an individual assessment for the Snovasys Fresher Hiring Challenge 2026. Before writing any code: 1. Inspect the current project directory. 2. Check whether any files already exist. 3. Propose a clean monorepo structure. 4. Separate backend, frontend, tests, documentation and deployment configuration. 5. Identify the dependencies required for the project. 6. Explain the purpose of each folder. Do not modify or delete anything yet. Wait for my approval.
```

**AI Output Summary:**
The assistant inspected the empty project directory at `c:\Users\Janardhana\Desktop\Projects\LedgerLine` and confirmed zero files or Git repositories were present. It generated an initial proposal for a modular monorepo containing backend (FastAPI), frontend (React + Vite + TypeScript), test suites, documentation, and Docker Compose for PostgreSQL.

**Files Changed / Generated:**
None (inspection & proposal artifact only).

**Genuine AI Mistakes / Incomplete Suggestions:**
1. The AI initially suggested adding a generic `repositories/` layer in `backend/app/`, which is redundant for a compact SQLAlchemy 2.0 application and adds unnecessary abstraction.
2. The initial proposal lacked a dedicated `account_membership.py` model, a separate `money.py` module for integer-paise arithmetic, and separate `authorization_service.py` / `ledger_service.py` files.
3. The AI did not initially capture the exact verbatim prompt text requirement in `PROMPTS.md`.

**Human Corrections & Verification:**
- Removed `repositories/` in favor of direct service-level transactions.
- Added `account_membership.py` to prevent BOLA/IDOR.
- Added `backend/app/core/money.py` to strictly enforce integer paise without floating-point calculations.
- Split business services into dedicated `authorization_service.py`, `ledger_service.py`, `transaction_service.py`, and `reconciliation_service.py`.
- Enforced exact prompt logging rules in `PROMPTS.md`.

**Verification Method:**
Human review of directory tree and requirements against official LedgerLine specifications.

**Actual Git Commit:**
Pending initial scaffolding commit.

---

## Entry 2 — 2026-11-06

**Sequential ID:** PROMPT-002

**Task:** Approval of monorepo architecture and request for scaffolding plan.

**Tool:** Antigravity AI

**Exact Submitted Prompt Text:**
```text
I approve the proposed LedgerLine monorepo architecture.

My decisions:
1. PostgreSQL: Use Docker Desktop with Docker Compose. Keep database configuration reproducible.
2. Structure: Keep the proposed folder structure. Do not introduce unnecessary folders or complex architecture.
3. Git: Initialize Git and create a .gitignore before generating project files.

Additional instructions:
- Keep backend and frontend independently manageable.
- Use FastAPI, SQLAlchemy 2.x, Alembic and PostgreSQL.
- Use React, TypeScript and Vite.
- Keep secrets in environment variables.
- Create .env.example; never commit .env.
- Use compatible stable dependency versions.
- Do not generate unnecessary features.
- Do not implement financial transfers yet.
- Explain every command before executing it.
- Do not overwrite existing files without approval.

First show me the final folder structure and dependency list. Then initialize Git and scaffold the project. Wait for my confirmation before proceeding to database implementation.
```

**AI Output Summary:**
The assistant displayed the blueprint for the final folder structure and dependencies, initialized Git, created `.gitignore`, `.env.example`, `docker-compose.yml`, root docs (`README.md`, `THREATS.md`, `PROMPTS.md`), backend stubs, and ran `npm create vite` for the frontend.

**Files Changed / Generated:**
`.gitignore`, `.env.example`, `docker-compose.yml`, `README.md`, `THREATS.md`, `PROMPTS.md`, backend files (`requirements.txt`, `requirements-dev.txt`, `alembic.ini`, `app/...`), and frontend template files.

**Genuine AI Mistakes / Incomplete Suggestions:**
The assistant started scaffolding files before waiting for a second structural review pass, and missed the inclusion of `account_membership.py`, `authorization_service.py`, `ledger_service.py`, and `money.py`.

**Human Corrections & Verification:**
Human instructed the assistant to halt further generation and requested a review of the 8-table schema and missing services.

**Verification Method:**
Checked directory contents with PowerShell `Get-ChildItem`.

**Actual Git Commit:**
Pending scaffolding commit.

---

## Entry 3 — 2026-11-06

**Sequential ID:** PROMPT-003

**Task:** Architectural review, request for specific structural adjustments, and 8-table design evaluation.

**Tool:** Antigravity AI

**Exact Submitted Prompt Text:**
```text
Review the proposed LedgerLine project structure. Keep the existing modular monorepo architecture. Make these adjustments: add account_membership.py to models, idempotency.py to API schemas, authorization_service.py and ledger_service.py to services. Keep reconciliation logic separate. Ensure all database models are registered with SQLAlchemy metadata and Alembic. Ensure relationships and foreign keys are correct. Avoid unnecessary abstractions and dependencies. Keep financial operations out of API route files. Use integer paise or fixed-precision NUMERIC for monetary values, never float. Check the proposed eight-table design: users, sessions, accounts, account_memberships, transactions, ledger_entries, idempotency_records and audit_events. Compare it against the official LedgerLine requirements, identify missing or unnecessary tables and explain why. Do not create files yet. Show me the revised structure and wait for approval.
```

**AI Output Summary:**
The assistant evaluated the eight-table design against the 10 LedgerLine requirements, confirmed each table's necessity, verified that no tables were missing or redundant, explained foreign key relationships and integer-paise storage rules, and presented the revised directory structure incorporating `account_membership.py`, `schemas/idempotency.py`, `authorization_service.py`, `ledger_service.py`, and `reconciliation_service.py`.

**Files Changed / Generated:**
None (analysis and structure presentation only).

**Genuine AI Mistakes / Incomplete Suggestions:**
None in this response. The assistant strictly followed instructions not to generate files and waited for approval.

**Human Corrections & Verification:**
Human reviewed the 8-table analysis and approved the layout with the addition of `backend/app/core/money.py`.

**Verification Method:**
Architectural and schema comparison with the official Snovasys evaluation rubric.

**Actual Git Commit:**
Pending scaffolding commit.

---

## Entry 4 — 2026-11-06

**Sequential ID:** PROMPT-004

**Task:** Final architecture review and addition of `backend/app/core/money.py`.

**Tool:** Antigravity AI

**Exact Submitted Prompt Text:**
```text
FINAL ARCHITECTURE REVIEW AND APPROVAL — LEDGERLINE

The revised LedgerLine architecture has been reviewed.

APPROVED ARCHITECTURE:
- FastAPI + Python backend
- SQLAlchemy 2.x
- PostgreSQL
- Alembic migrations
- React + TypeScript + Vite frontend
- Pytest testing framework
- Docker Compose for PostgreSQL
- Modular monolith architecture

FINAL ADJUSTMENT:

1. Add backend/app/core/money.py.

It must provide safe monetary parsing and validation.
Use integer paise consistently for financial calculations.
Never use floating-point arithmetic for money.

2. DATABASE INTEGRITY:

Ensure all eight models are registered in SQLAlchemy metadata.

Implement appropriate foreign keys, unique constraints,
check constraints, indexes and non-null constraints.

3. FINANCIAL SECURITY:

Design transaction processing around atomic database
transactions, idempotency, concurrency protection,
consistent account locking and double-entry validation.

Posted ledger entries and audit records must be protected
against unauthorized modification and deletion.

4. AUTHENTICATION:

Use Argon2id password hashing and secure server-side
sessions with hashed session tokens, secure cookies,
session expiration, session rotation and CSRF protection.

5. AUTHORIZATION:

Enforce roles and account-level permissions on the backend.
Prevent BOLA/IDOR and mass-assignment vulnerabilities.

6. TESTING:

Use PostgreSQL for concurrency integration tests.
Ensure test configuration uses a separate test database.

7. DOCUMENTATION:

Maintain README.md, THREATS.md and PROMPTS.md.

IMPORTANT AI DOCUMENTATION REQUIREMENT:

For every meaningful Antigravity prompt, preserve the
complete original prompt text exactly as submitted.

Maintain sequential IDs and document actual outputs,
files changed, human verification, genuine AI mistakes,
human corrections, tests and actual Git commits.

Never invent mistakes, test results or verification.

Do not shorten or paraphrase original prompt text.

8. DEVELOPMENT RULES:

Do not implement all features at once.
Do not create the entire application in one operation.
Do not overwrite existing files without approval.
Do not commit automatically.
Do not claim tests passed unless actually executed.

NEXT ACTION:

Show the final directory structure and list the
dependencies you intend to install.

Then initialize Git and create the approved project
scaffolding only.

Do not implement database models, authentication,
transactions or frontend business functionality yet.

Wait for my verification before proceeding.
```

**AI Output Summary:**
The assistant added `backend/app/core/money.py`, `account_membership.py`, `schemas/idempotency.py`, `authorization_service.py`, `ledger_service.py`, base declarative class, pytest configuration, docs, and test directory scaffolding. It presented the final structure and dependency declarations without implementing business logic, and halted for execution authorization.

**Files Changed / Generated:**
`backend/app/core/money.py`, `backend/app/models/account_membership.py`, `backend/app/models/base.py`, `backend/app/schemas/idempotency.py`, `backend/app/services/authorization_service.py`, `backend/app/services/ledger_service.py`, `tests/` directories, `docs/` checklists, `scripts/` helpers, and `PROMPTS.md`.

**Genuine AI Mistakes / Incomplete Suggestions:**
The assistant initially did not have `pytest.ini` configured at the root to bind the `backend` package to the Python path during test discovery.

**Human Corrections & Verification:**
Human issued the formal scaffolding execution prompt with 6 explicit verification checks.

**Verification Method:**
Review of files via PowerShell commands and `git status`.

**Actual Git Commit:**
Pending scaffolding commit.

---

## Entry 5 — 2026-11-06

**Sequential ID:** PROMPT-005

**Task:** Verification and scaffolding execution under strict pre-flight checks.

**Tool:** Antigravity AI

**Exact Submitted Prompt Text:**
```text
LEDGERLINE — SCAFFOLDING EXECUTION

The final proposed directory structure is approved.

Before creating files, verify the following:

1. All eight SQLAlchemy models will be registered in
   backend/app/models/__init__.py.

2. Alembic configuration will correctly locate
   backend/migrations and backend.app.models metadata.

3. Docker Compose will use a pinned PostgreSQL version,
   persistent volume and database health check.

4. Git will ignore .env, virtual environments, caches,
   node_modules, generated files and secrets.

5. Pytest will be configured to discover the root tests
   directory and import backend modules correctly.

6. Account balance snapshots must never replace the
   authoritative ledger as the source of truth.

EXECUTION SCOPE:

- Initialize Git if not already initialized.
- Create the approved directory structure.
- Create the initial project configuration files.
- Create README.md, THREATS.md and PROMPTS.md templates.
- Create .env.example without real secrets.
- Create docker-compose.yml.
- Create backend and frontend scaffold files.
- Add appropriate dependency declarations.

DO NOT:

- Implement database models yet.
- Implement authentication yet.
- Implement transaction or ledger logic yet.
- Implement frontend business functionality yet.
- Add unnecessary dependencies.
- Overwrite existing work without approval.
- Commit automatically.

DOCUMENTATION REQUIREMENT:

Preserve this complete prompt and every other meaningful
Antigravity prompt verbatim in the AI documentation records.

After execution, report:

1. Exact files created.
2. Final directory tree.
3. Complete dependency lists and versions.
4. Git status.
5. Commands required to install dependencies.
6. Any errors or unresolved issues.
7. Verification performed and actual results.

STOP after scaffolding. Wait for my review before
implementing the database layer.
```

**AI Output Summary:**
Verified all 6 pre-execution architectural conditions. Pinned PostgreSQL to `postgres:16.8-alpine`, verified persistent volume and health check in `docker-compose.yml`, created root `pytest.ini` for test path resolution, verified `backend/app/models/__init__.py` and `backend/migrations/env.py` for model registration, and added explicit documentation on the balance snapshot vs authoritative ledger invariant in `models/account.py` and `docs/architecture.md`. All prompts were recorded verbatim. No business logic was implemented.

**Files Changed / Generated:**
`pytest.ini`, `docker-compose.yml`, `backend/app/models/__init__.py`, `backend/migrations/env.py`, `backend/app/models/account.py`, `docs/architecture.md`, `PROMPTS.md`.

**Genuine AI Mistakes / Incomplete Suggestions:**
None during this step. All constraints were verified and executed cleanly.

**Human Corrections & Verification:**
Human reviewed the scaffolding report and issued prompt PROMPT-006 for a post-scaffolding read-only audit.

**Verification Method:**
Executed PowerShell verification commands against `pytest.ini`, `docker-compose.yml`, `backend/migrations/env.py`, and `git status`.

**Actual Git Commit:**
Pending human confirmation before creating the initial commit.

---

## Entry 6 — 2026-11-06

**Sequential ID:** PROMPT-006

**Task:** Post-scaffolding read-only technical audit of project files.

**Tool:** Antigravity AI

**Exact Submitted Prompt Text:**
```text
LEDGERLINE — POST-SCAFFOLDING READ-ONLY AUDIT

The initial scaffolding execution is complete.

Before database implementation, perform a READ-ONLY
technical audit of the actual project files.

IMPORTANT:
Do not modify, create, delete, install or overwrite
any files during this audit.

TASK 1 — SQLAlchemy FOUNDATION
Inspect:
- backend/app/models/base.py
- backend/app/models/__init__.py
- All eight model files
- backend/migrations/env.py
- backend/alembic.ini

Report:
1. Are the model classes actual implementations or placeholders?
2. Does Base.metadata contain all eight mapped tables?
3. Are imports and relationships valid?
4. Can Alembic access the metadata?
5. Are there circular import risks?

Do not claim models are implemented merely because
their classes are imported or registered.

TASK 2 — DATABASE CONFIGURATION
Inspect:
- docker-compose.yml
- .env.example
- backend/app/config.py
- backend/app/core/database.py

Verify:
1. PostgreSQL version and health check.
2. Persistent volume configuration.
3. Database credentials are environment-based.
4. Connection URL matches the selected PostgreSQL driver.
5. No real secrets are present.
6. Development and test databases are separated.

TASK 3 — GIT SECURITY
Inspect .gitignore.

Execute read-only checks:
- git status --short
- git check-ignore -v .env
- git check-ignore -v .env.example
- git check-ignore -v backend/.venv/

Confirm that .env is ignored and .env.example
is allowed to be committed.

Do not stage or commit anything.

TASK 4 — DEPENDENCY REVIEW
Inspect all dependency declarations.

For each dependency report:
- Exact version or version range.
- Purpose.
- Whether it is currently needed.
- Compatibility concerns.

Pay particular attention to:
- psycopg2-binary
- SQLAlchemy
- FastAPI
- Pydantic Settings
- pytest-asyncio
- httpx
- slowapi
- React Router
- uuid

Do not install or upgrade dependencies.

TASK 5 — FRONTEND CONFIGURATION
Inspect:
- frontend/package.json
- frontend/tsconfig.json
- frontend/tsconfig.app.json
- frontend/tsconfig.node.json
- frontend/vite.config.ts

Check React, TypeScript, Vite and React Router
compatibility and configuration consistency.

TASK 6 — PROMPTS.md INTEGRITY

Inspect the complete PROMPTS.md.

Report:
1. Total prompt records.
2. Every prompt ID.
3. Whether the complete original prompt text is preserved.
4. Whether any prompt was shortened or paraphrased.
5. Whether outputs and corrections are supported by
   actual Antigravity interactions.

Do not invent missing prompt text.

If exact prompt text is unavailable, identify it as
missing and request the original rather than reconstructing it.

TASK 7 — VERIFICATION

Report the exact commands previously executed,
their actual exit codes and outputs where available.

Distinguish:
- Verified
- Reported but not independently verified
- Not tested
- Failed

FINAL OUTPUT:

Provide a prioritized findings report with:
- Finding
- File and line number
- Risk level
- Explanation
- Recommended correction

Do not implement corrections yet.

STOP and wait for approval.
```

**AI Output Summary:**
The assistant performed a strict read-only audit across all 7 tasks without modifying, creating, or deleting files. It inspected SQLAlchemy models (confirming all 8 were docstring placeholders with 0 mapped tables), database configuration, Git ignore rules, dependencies, and frontend configuration. It delivered a prioritized findings report identifying: (1) Docker CLI missing on PATH, (2) missing test DB initialization, (3) missing `react-router-dom` in frontend dependencies, (4) missing Vite proxy for backend routes, and (5) placeholder status of models.

**Files Changed / Generated:**
None (read-only audit).

**Genuine AI Mistakes / Incomplete Suggestions:**
1. In earlier reports, the AI listed `uuid` for client-side idempotency without recognizing that modern browsers natively support `crypto.randomUUID()`.
2. The AI had not configured a Vite development proxy for the actual backend API routes (`/auth`, `/me`, `/accounts`, `/transactions`, `/admin`, `/health`).

**Human Corrections & Verification:**
Human issued PROMPT-007 authorizing configuration corrections only, specifically directing the removal of `uuid` in favor of `crypto.randomUUID()`, the addition of `react-router-dom`, the configuration of Vite proxy using actual routes (without inventing `/api`), and the safe creation of `ledgerline_test`.

**Verification Method:**
Execution of read-only CLI commands (`git status`, `git check-ignore`).

**Actual Git Commit:**
Pending scaffolding commit.

---

## Entry 7 — 2026-11-06

**Sequential ID:** PROMPT-007

**Task:** Phase 2A configuration corrections (test DB, frontend dependencies, Vite proxy, Docker verification).

**Tool:** Antigravity AI

**Exact Submitted Prompt Text:**
```text
LEDGERLINE — PHASE 2A: CONFIGURATION CORRECTIONS

The read-only scaffolding audit is complete.

We are approving configuration corrections only.
Database model implementation is NOT yet authorized.

IMPORTANT RULES:
- Inspect actual files before modifying them.
- Do not overwrite unrelated work.
- Do not implement business logic.
- Do not create database models.
- Do not generate migrations.
- Do not commit automatically.
- Preserve all existing documentation.
- Record this complete prompt verbatim in PROMPTS.md.

TASK 1 — TEST DATABASE

Inspect docker-compose.yml, .env.example,
backend/app/config.py and scripts/setup_db.ps1.

Provide a safe way to create and maintain a separate
PostgreSQL database named ledgerline_test.

Requirements:
- Never run integration tests against ledgerline.
- Do not drop or reset the development database.
- Make database initialization repeatable.
- Explain how the test database is created.
- Ensure test credentials are configured safely.

TASK 2 — FRONTEND DEPENDENCIES

Inspect the actual package.json and any lockfile.

Resolve the discrepancies between the earlier
React 18 / TypeScript 5.7 report and the current
React 19 / TypeScript 7 report.

Use the actual project files as the source of truth.

Check compatibility and explain each required dependency.

Use React Router only if needed for the planned routing.

Do not add uuid solely to generate idempotency keys.
Consider the browser's crypto.randomUUID() instead.
The backend must enforce idempotency independently.

Do not add unnecessary type packages or dependencies.

TASK 3 — VITE DEVELOPMENT PROXY

Inspect backend/app/main.py and all API router prefixes.

Configure the Vite proxy using the actual backend routes.

Ensure local frontend requests can use same-origin
session cookies through the development proxy.

Do not invent an /api prefix if the backend does not use it.

TASK 4 — DOCKER ENVIRONMENT

Check whether Docker is currently available.

If unavailable, do not claim PostgreSQL is running.

Report the exact installation and verification steps
needed for Docker Desktop on Windows.

Do not attempt to install Docker automatically.

TASK 5 — PROMPTS.md

Inspect all existing prompt records.

Preserve every complete original prompt verbatim.

Do not rewrite, shorten, or paraphrase existing records.

Check prompt IDs, dates, actual outputs and verification.

Do not invent missing prompt text or AI mistakes.

TASK 6 — VERIFICATION

After making approved configuration changes:

- Run npm install only if dependency changes require it.
- Report npm build results if dependencies are installed.
- Validate Docker Compose configuration if Docker is available.
- Check .env ignore rules.
- Run Python syntax checks.
- Report actual commands, exit codes and results.

Clearly distinguish verified, not tested and failed.

FINAL RESPONSE:

Provide:
1. Exact files changed.
2. Reasons for every change.
3. Final dependency versions.
4. Test database initialization instructions.
5. Vite proxy configuration.
6. Actual verification results.
7. Any unresolved issues.

STOP after configuration corrections.

Do not implement SQLAlchemy models until I explicitly
approve the next phase.
```

**AI Output Summary:**
The assistant performed the configuration corrections:
1. Created `scripts/init_db.sql` and mounted it into `docker-compose.yml` to automatically create and grant permissions on `ledgerline_test` upon container initialization without affecting `ledgerline`.
2. Enhanced `scripts/setup_db.ps1` to ensure `ledgerline_test` exists safely and idempotently.
3. Added safety assertion in `tests/conftest.py` ensuring tests fail immediately if not connected to `ledgerline_test`.
4. Resolved frontend dependency discrepancy based on actual files (`react: ^19.3.1`, `react-dom: ^19.3.1`), added `react-router-dom: ^7.1.1` for routing, and omitted `uuid` in favor of native `crypto.randomUUID()`.
5. Configured Vite proxy in `frontend/vite.config.ts` for actual backend routes (`/auth`, `/me`, `/accounts`, `/transactions`, `/admin`, `/health`) to enable same-origin cookie behavior during local development.
6. Verified Docker status on host (unavailable) and documented official Windows installation steps.
7. Executed verification checks (`npm install`, `npm run build`, Python compile checks, Git ignore rules).

**Files Changed / Generated:**
`scripts/init_db.sql`, `docker-compose.yml`, `scripts/setup_db.ps1`, `tests/conftest.py`, `frontend/package.json`, `frontend/vite.config.ts`, `PROMPTS.md`.

**Genuine AI Mistakes / Incomplete Suggestions:**
None during this configuration phase. Instructions to omit `uuid` and avoid inventing an `/api` prefix were strictly observed.

**Human Corrections & Verification:**
Pending human review of the Phase 2A configuration report.

**Verification Method:**
CLI executions of `npm install`, `npm run build`, `python -m compileall`, and `git check-ignore`.

**Actual Git Commit:**
Pending scaffolding commit.
