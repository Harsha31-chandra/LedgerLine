# LedgerLine

**Money movement with a ledger you can prove.**

> A simulated financial transaction system built for the Snovasys Fresher Hiring Challenge 2026 (VVIT). This is an assessment project using simulated money — it is not a real bank or payment service.

## Overview

LedgerLine moves money between accounts while proving that money is never created, lost or moved twice. Every operation is processed in one PostgreSQL transaction with row-level locks, balanced double-entry ledger postings, idempotency protection, and a complete audit trail.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + FastAPI |
| Database | PostgreSQL 16 (via Docker) |
| ORM / Migrations | SQLAlchemy 2.x + Alembic |
| Frontend | React 18 + TypeScript + Vite |
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
| Admin | admin@ledgerline.com | admin123 |
| Account Holder | holder@ledgerline.com | holder123 |
| Auditor | auditor@ledgerline.com | auditor123 |

> ⚠️ These are demo-only credentials for evaluation. Do not use in production.

## Role Matrix

| Capability | Admin | Account Holder | Auditor |
|-----------|-------|---------------|---------|
| Create/freeze accounts | ✅ | ❌ | ❌ |
| View all accounts | ✅ | Own only | Read-only all |
| Deposit/withdraw | Controlled | Own account | ❌ |
| Transfer | Controlled | From own account | ❌ |
| View audit trail | ✅ | Own events | Read-only |
| Edit/delete ledger | ❌ Never | ❌ Never | ❌ Never |

## Money Invariants

1. Every posted transaction balances: total debit = total credit.
2. No wallet balance falls below zero.
3. Internal transfers leave the sum of customer wallets unchanged.
4. One idempotency key maps to at most one financial effect.
5. Balance snapshots equal the balance derived from posted ledger entries.

## Database Environment Isolation

LedgerLine strictly isolates development, testing, and migration database environments:

- **`DATABASE_URL`**: Used exclusively for application development runtime (`ledgerline`). Never used for tests or migration commands.
- **`TEST_DATABASE_URL`**: Used exclusively by Pytest for automated test execution (`ledgerline_test` on `localhost:5432`). Programmatically rejects connections targeting `ledgerline`.
- **`MIGRATION_DATABASE_URL`**: Required explicitly for all Alembic commands. Never falls back to `DATABASE_URL` or application settings. During initial development, migrations must target `ledgerline_test` on `localhost:5432`. No migration command can silently execute against the development database.

## Database Schema & Migration Status

- **Baseline Migration:** `7717a26bd3d3_initial_schema` ([`backend/migrations/versions/7717a26bd3d3_initial_schema.py`](backend/migrations/versions/7717a26bd3d3_initial_schema.py)).
- **Target Database:** Verified and applied exclusively to the isolated test database `ledgerline_test`.
- **Schema Contents:** 8 application domain tables (`users`, `sessions`, `accounts`, `account_memberships`, `transactions`, `ledger_entries`, `idempotency_records`, `audit_events`), 58 columns, 8 foreign keys (`ondelete` safeguards: `RESTRICT` on `ledger_entries` protects referenced parent accounts/transactions from deletion, `SET NULL` on audit/transaction initiators, `CASCADE` on memberships/sessions/idempotency), 9 check constraints, 2 composite unique constraints, 18 indexes, and `alembic_version`.
- **Schema Drift Check:** Verified clean via `python -m alembic -c backend\alembic.ini check` (`No new upgrade operations detected`).
- **Development Database Status:** The initial migration was applied to `ledgerline_test`. The development database (`ledgerline`) was not targeted by that migration, and its complete contents have not been independently verified.
- **Implementation Status:** Application business logic (authentication, authorization, transfer processing, and double-entry ledger posting) is scheduled for subsequent implementation phases.

## Remaining Engineering Considerations

The following capabilities are deliberately distinguished from the initial database foundation and represent upcoming implementation work:
- Atomic double-entry ledger posting and debit/credit balancing in service layer (`ledger_service.py`).
- Database-enforced immutability for posted ledger entries (currently, `ON DELETE RESTRICT` protects parent records from deletion, but does not prevent direct `UPDATE` or `DELETE` on ledger entries; database-enforced append-only behavior via role permissions or triggers remains a future requirement).
- Server-side database triggers for automatic `updated_at` refresh on raw SQL updates.
- Engine-level PostgreSQL row-level security (RLS), if required by the threat model.

## Running Tests

Configured via `pytest.ini` with 48 automated unit tests verifying models, check constraints, relationship back-populations, and database isolation safety:

```powershell
pytest -q
```
*Current test result:* **48 passed in 2.58s** (0 warnings).

## Documentation & AI Usage Log

- **Architecture Details:** See [`docs/architecture.md`](docs/architecture.md) for domain service design and invariant specifications.
- **AI Usage Log:** See [`PROMPTS.md`](PROMPTS.md) for the complete, verbatim prompt history and independent audit trail.

## API Documentation

When the backend is running: http://localhost:8000/docs

## Live URL

*To be added after deployment.*

## Limitations

*To be documented as development progresses.*
