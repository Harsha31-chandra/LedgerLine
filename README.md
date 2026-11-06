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
# Edit .env if needed

# 5. Run migrations
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

## Running Tests

```powershell
pytest -q
```

## API Documentation

When the backend is running: http://localhost:8000/docs

## Live URL

*To be added after deployment.*

## Limitations

*To be documented as development progresses.*
