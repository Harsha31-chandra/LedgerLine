# LedgerLine — Render Deployment Guide
**Assessment:** Snovasys Fresher Hiring Challenge 2026  
**Target Platform:** Render Cloud Platform ([render.com](https://render.com))  
**Deployment Type:** Containerized Multi-Tier Web Services (Docker)

---

## 1. Architectural Overview & Topology

LedgerLine deploys on Render using a decoupled three-tier containerized topology:

```
┌─────────────────────────────────────────────────────────────┐
│  Browser Client (User / Evaluator)                          │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTPS (Same-Origin)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  Frontend Web Service (Render Free Docker Web Service)       │
│  - Container: Nginx 1.27 + React 18 SPA (Vite Production)    │
│  - Public URL: https://ledgerline-frontend.onrender.com     │
│  - Static Assets: / (index.html, JS/CSS bundles)            │
│  - Reverse Proxy: /auth, /accounts, /transactions, /admin    │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTPS Upstream Proxy (TLS/SNI)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  Backend Web Service (Render Free Docker Web Service)        │
│  - Container: FastAPI + Python 3.12 (Uvicorn, Non-Root)     │
│  - Public URL: https://ledgerline-backend.onrender.com      │
│  - Endpoints: /health, /docs, /auth, /accounts, /audit      │
│  - Role: ledgerline_app (least-privilege DML only)          │
└──────────────────────────────┬──────────────────────────────┘
                               │ Private PostgreSQL Network
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  Render Managed Database (Render Free PostgreSQL 16)         │
│  - Host: dpg-xxxxxx-a.oregon-postgres.render.com            │
│  - Database: ledgerline                                     │
│  - Schema Owner: ledgerline_migrator (DDL)                  │
│  - Runtime User: ledgerline_app (DML: SELECT, INSERT)       │
└─────────────────────────────────────────────────────────────┘
```

### Why Same-Origin Reverse Proxy on Render?
Because `onrender.com` is listed on the **Public Suffix List (PSL)**, `frontend.onrender.com` and `backend.onrender.com` are treated by modern browsers as separate cross-site origins. Direct browser-to-backend requests would require third-party cookies (`SameSite=None; Secure`), which modern browsers (Safari, Chrome, Firefox) increasingly block by default.

By using Nginx to reverse-proxy all API routes under the frontend origin:
- All cookies (`ledgerline_session`) remain **First-Party** (`SameSite=Lax`).
- Browser cross-origin preflight `OPTIONS` requests are eliminated.
- CSRF origin checking strictly validates against the frontend domain.

---

## 2. Render Free-Tier Limitations & Realities

Before deploying on Render's free tier, understand these operational constraints:

| Constraint | Render Free Tier Specification | Impact on LedgerLine |
| :--- | :--- | :--- |
| **PostgreSQL Expiration** | Free databases expire **30 days** after creation. | **Evaluation Only:** Intended for 30-day assessment demos. Permanent deployment requires an external or paid PostgreSQL instance. |
| **Service Inactivity (Sleeping)** | Web services spin down after **15 minutes** of inactivity. | First incoming request after sleep will experience a **50–60 second cold-start delay**. |
| **Ephemeral Disks** | Free web service containers have ephemeral storage. | No impact; LedgerLine stores all state and ledger data in PostgreSQL. |
| **Single-Node Rate Limiting** | SlowAPI rate limiting is stored in-memory. | Process-local; sufficient for evaluation demos. |
| **Resource Limits** | 0.1 CPU, 512 MB RAM per free service. | Fully sufficient for FastAPI and Nginx Alpine images. |

---

## 3. Step-by-Step Deployment Procedure

### Step 1: Push Repository to GitHub (When Authorized)
Once explicitly authorized, commit and push the clean repository to GitHub:
```powershell
git push origin master
```

---

### Step 2: Provision Render PostgreSQL Database
1. In the Render Dashboard, click **New +** $\to$ **PostgreSQL**.
2. Configure:
   - **Name:** `ledgerline-db`
   - **Database:** `ledgerline`
   - **User:** `ledgerline` (Render bootstrap admin)
   - **Region:** `Oregon` (or region closest to evaluator)
   - **Plan:** `Free`
3. Click **Create Database**.
4. Once created, note the **Internal Database URL** and **External Database URL**.

---

### Step 3: Initialize Database Roles (Least-Privilege Setup)
LedgerLine strictly enforces three-tier role separation (`validate_runtime_database_url` rejects connecting as superusers or admin roles). You must run the role initialization script once against the new database:

1. Copy the **External Connection String** from the Render database dashboard.
2. From your local terminal (or any machine with `psql`), execute `scripts/init_db.sql`:
   ```bash
   psql "<RENDER_EXTERNAL_CONNECTION_STRING>" -f scripts/init_db.sql
   ```
   *(Note: replace placeholder passwords in `init_db.sql` with strong production passwords before executing).*
3. Verify roles created:
   - `ledgerline_migrator`: Schema owner and migration executor.
   - `ledgerline_app`: Runtime application user (cannot modify table structures or drop triggers).

---

### Step 4: Run Alembic Database Migrations
Run migrations using the schema-owner role (`ledgerline_migrator`):

```powershell
$env:MIGRATION_DATABASE_URL="postgresql://ledgerline_migrator:<MIGRATOR_PASSWORD>@<EXTERNAL_HOST>:5432/ledgerline"
$env:APP_ENV="production"
$env:DB_ALLOWED_HOSTS="<EXTERNAL_HOST>"
$env:DB_ALLOWED_DATABASES="ledgerline"
$env:DB_ALLOWED_PORTS="5432"

.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

Verify that the output shows all migrations applied up to `d4a72e81bc34 (head)`.

---

### Step 5: Deploy Backend Web Service
1. In Render, click **New +** $\to$ **Web Service**.
2. Select your connected GitHub repository: `Harsha31-chandra/LedgerLine`.
3. Configure:
   - **Name:** `ledgerline-backend`
   - **Language / Environment:** `Docker`
   - **Docker Context:** `backend`
   - **DockerfilePath:** `backend/Dockerfile`
   - **Region:** Same region as database (`Oregon`)
   - **Plan:** `Free`
   - **Health Check Path:** `/health`
4. Configure **Environment Variables**:

| Variable | Value | Notes |
| :--- | :--- | :--- |
| `APP_ENV` | `production` | Enables fail-closed production security checks |
| `PORT` | `10000` | Render standard port |
| `APP_DATABASE_URL` | `postgresql://ledgerline_app:<APP_PASSWORD>@<INTERNAL_DB_HOST>:5432/ledgerline` | Internal Render network URL |
| `DATABASE_URL` | `postgresql://ledgerline_app:<APP_PASSWORD>@<INTERNAL_DB_HOST>:5432/ledgerline` | Same as `APP_DATABASE_URL` |
| `DB_ALLOWED_HOSTS` | `<INTERNAL_DB_HOST>` | Host portion of Render internal DB |
| `DB_ALLOWED_DATABASES` | `ledgerline` | Target database name |
| `DB_ALLOWED_PORTS` | `5432` | Standard port |
| `SESSION_SECRET` | *(Click 'Generate' in Render for 32+ char key)* | Session HMAC secret |
| `SESSION_COOKIE_NAME` | `ledgerline_session` | Standard cookie name |
| `SESSION_TTL_MINUTES` | `1440` | 24-hour expiration |
| `COOKIE_SECURE` | `true` | Enforces HTTPS-only cookie transmission |
| `FORWARDED_ALLOW_IPS` | `*` | Trusts Render reverse proxy headers |
| `CORS_ORIGINS` | `https://ledgerline-frontend.onrender.com` | Match future frontend URL |

5. Click **Create Web Service**. Wait for build to complete and health check to report green.
6. Test endpoint: `curl https://ledgerline-backend.onrender.com/health` $\to$ `{"status":"healthy","service":"ledgerline"}`.

---

### Step 6: Deploy Frontend Web Service
1. In Render, click **New +** $\to$ **Web Service**.
2. Select your connected GitHub repository: `Harsha31-chandra/LedgerLine`.
3. Configure:
   - **Name:** `ledgerline-frontend`
   - **Language / Environment:** `Docker`
   - **Docker Context:** `frontend`
   - **DockerfilePath:** `frontend/Dockerfile`
   - **Region:** Same region (`Oregon`)
   - **Plan:** `Free`
   - **Health Check Path:** `/`
4. Configure **Environment Variables**:

| Variable | Value | Notes |
| :--- | :--- | :--- |
| `PORT` | `80` | Nginx template port (Render maps to 80/10000) |
| `BACKEND_PUBLIC_URL` | `https://ledgerline-backend.onrender.com` | Backend service public HTTPS URL |

5. Click **Create Web Service**.
6. Once deployed, open `https://ledgerline-frontend.onrender.com` in your browser.

---

## 4. Post-Deployment Verification Checklist

Verify the deployed cloud application in order:

- [ ] `GET /health` on frontend proxy returns `200 OK` (`{"status":"healthy","service":"ledgerline"}`).
- [ ] `GET /docs` on frontend proxy opens Swagger OpenAPI UI.
- [ ] User registration at `/register` creates an account and sets `ledgerline_session` cookie with `HttpOnly; Secure; SameSite=Lax`.
- [ ] First-time onboarding displays the Onboarding Welcome Hero.
- [ ] Account creation succeeds with ₹10,000 demo opening deposit.
- [ ] Deposit, withdrawal, and transfer update account balance.
- [ ] Statements page displays posted chronological transactions.
- [ ] Sign out clears the session cookie and redirects to `/login`.
- [ ] Auditor login demonstrates read-only mode and rejects mutations.

---

## 5. Security & Assessment Disclosure: `PRODUCTION USE BLOCKED`

> [!WARNING]
> **ASSESSMENT & DEMO LEDGER ONLY — PRODUCTION FINANCIAL USE BLOCKED**
> 
> LedgerLine is designed for technical evaluation in the **Snovasys Fresher Hiring Challenge 2026**.
> 
> While LedgerLine implements rigorous application-level authorization, Argon2id password hashing, double-entry mathematical invariants, and database-level trigger immutability, **production financial deployment with real customer money is BLOCKED** due to the following residual limitations:
> 
> 1. **PostgreSQL Row-Level Security (RLS) is Disabled:** Isolation is enforced at the application/ORM service layer. Direct database connections under the application role are not restricted by database-level row visibility policies.
> 2. **Process-Local Rate Limiting:** Single-node in-memory rate limiting does not provide cluster-wide distributed DDoS protection.
> 3. **Single-Region Infrastructure:** Lacks automated multi-region replication, continuous read-replica failover, and hardware security module (HSM) key storage.
> 4. **No Real Banking Rails:** Simulated money and central clearing model; not integrated with actual RTGS/NEFT/IMPS or automated clearinghouse gateways.
