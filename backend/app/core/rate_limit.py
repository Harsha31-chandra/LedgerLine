"""
Rate-limiting configuration and exception handling for LedgerLine.

Provides:
- SlowAPI Limiter configured with client IP key resolution.
- Standard JSON response handler for HTTP 429 RateLimitExceeded errors,
  ensuring sensitive authentication and internal timing details are not leaked.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Shared application rate limiter using client IP
limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a generic HTTP 429 response without leaking internal state or credentials."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
    )
