"""
LedgerLine — FastAPI application entry point.

Provides:
- Health check endpoint at GET /health
- Middleware stack: CORS, CSRF Origin protection, and SlowAPI rate limiting
- API routers: Auth (/auth), Accounts (/accounts), and Transactions (/transactions)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.app.api.accounts import router as accounts_router
from backend.app.api.admin import router as admin_router
from backend.app.api.auth import router as auth_router
from backend.app.api.transactions import router as transactions_router
from backend.app.config import settings
from backend.app.core.csrf import CSRFProtectMiddleware
from backend.app.core.rate_limit import limiter, rate_limit_exceeded_handler

app = FastAPI(
    title="LedgerLine",
    description="Money movement with a ledger you can prove.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# 1. Rate limiting configuration
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# 2. CSRF Origin & Referer protection for state-changing methods
app.add_middleware(
    CSRFProtectMiddleware,
    allowed_origins=settings.cors_origins_list,
)

# 3. CORS — outermost middleware to handle browser preflight OPTIONS requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# 4. API Routers
app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(transactions_router)
app.include_router(admin_router)


@app.get("/health", tags=["ops"])
def health_check():
    """Return service status. Used by Docker health checks and uptime monitors."""
    return {"status": "healthy", "service": "ledgerline"}
