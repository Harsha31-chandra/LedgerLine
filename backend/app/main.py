"""
LedgerLine — FastAPI application entry point.

Provides:
- Health check endpoint at GET /health
- CORS configuration
- Router registration (to be added as routes are implemented)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings

app = FastAPI(
    title="LedgerLine",
    description="Money movement with a ledger you can prove.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow the frontend dev server origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["ops"])
def health_check():
    """Return service status. Used by Docker health checks and uptime monitors."""
    return {"status": "healthy", "service": "ledgerline"}
