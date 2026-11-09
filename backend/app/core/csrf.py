"""
Cross-Site Request Forgery (CSRF) protection middleware for LedgerLine.

Provides:
- Trustworthy Origin and Referer validation on all state-changing HTTP methods
  (POST, PUT, PATCH, DELETE).
- Strict whitelist enforcement matching explicitly configured trusted origins
  (from application settings; no dynamic Host-header trust).
- Exact canonical origin normalization (scheme, host, and port).
- Rejection of missing, empty, malformed, or untrusted origin headers with HTTP 403 Forbidden.
- Rejection of opaque origins (e.g. Origin: null) with HTTP 403 Forbidden.
- Safe pass-through for read-only idempotent methods (GET, HEAD, OPTIONS).
"""

from collections.abc import Iterable
import ipaddress
import urllib.parse

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


def _is_ipv6(hostname: str) -> bool:
    """Check if a hostname string represents a valid IPv6 address."""
    try:
        ip = ipaddress.ip_address(hostname)
        return isinstance(ip, ipaddress.IPv6Address)
    except ValueError:
        return False


def _normalize_origin(raw: str, is_origin_header: bool = False) -> str | None:
    """Parse and normalize an origin or referer string into canonical (scheme://host[:port]).

    Args:
        raw: The raw header string to normalize.
        is_origin_header: Whether the input is an Origin header (enforces strict origin syntax,
            rejecting user-info, query parameters, fragments, or subpaths).

    Returns:
        Canonical origin string (e.g. 'http://localhost:5173', 'http://[::1]:8000') or None if invalid.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None

    cleaned = raw.strip()
    if cleaned.lower() == "null":
        return None

    try:
        parsed = urllib.parse.urlsplit(cleaned)
    except ValueError:
        return None

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return None

    # Origin header strict syntax verification (RFC 6454)
    if is_origin_header:
        # User-information components are forbidden in Origin headers
        if "@" in parsed.netloc or parsed.username is not None or parsed.password is not None:
            return None
        # Origin headers must not contain query parameters or fragments
        if parsed.query or parsed.fragment:
            return None
        # Origin headers must not contain paths (except an optional single '/')
        if parsed.path and parsed.path != "/":
            return None

    try:
        hostname = parsed.hostname
    except ValueError:
        return None

    if not hostname:
        return None

    # Reject empty port specifications (e.g. 'http://localhost:')
    if parsed.netloc.endswith(":"):
        return None

    # Safely access port, catching out-of-range, non-integer, or malformed values
    try:
        port = parsed.port
    except ValueError:
        return None

    if port is not None and (port < 1 or port > 65535):
        return None

    # IPv6 literal canonicalization: retain square brackets per RFC 3986
    if _is_ipv6(hostname):
        formatted_host = f"[{hostname.lower()}]"
    else:
        formatted_host = hostname.lower()

    # Omit default ports for canonical representation
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        canonical_netloc = formatted_host
    else:
        canonical_netloc = f"{formatted_host}:{port}"

    return f"{scheme}://{canonical_netloc}"


class CSRFProtectMiddleware(BaseHTTPMiddleware):
    """Enforces strict Origin/Referer verification on state-changing HTTP requests.

    Protects against Cross-Site Request Forgery (CSRF) for cookie-authenticated
    and state-changing endpoints (POST, PUT, PATCH, DELETE).

    Policies:
    - Safe methods (GET, HEAD, OPTIONS) bypass CSRF checks.
    - If Origin is provided, it must match explicitly configured trusted origins.
    - If Origin is missing, Referer's origin must match explicitly configured trusted origins.
    - If both Origin and Referer are missing, untrusted, or malformed, the request
      is rejected with HTTP 403 Forbidden.
    - Never derives trusted origins from incoming client Host or request headers.
    """

    def __init__(self, app, allowed_origins: Iterable[str]) -> None:
        super().__init__(app)
        normalized = set()
        for origin in allowed_origins:
            norm = _normalize_origin(origin, is_origin_header=False)
            if norm:
                normalized.add(norm)
        self.allowed_origins: frozenset[str] = frozenset(normalized)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            raw_origin = request.headers.get("origin")
            raw_referer = request.headers.get("referer")

            # 1. Evaluate Origin header if present
            if raw_origin is not None:
                norm_origin = _normalize_origin(raw_origin, is_origin_header=True)
                if not norm_origin or norm_origin not in self.allowed_origins:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF verification failed: untrusted origin"},
                    )
            # 2. If Origin is absent, fallback to Referer header
            elif raw_referer is not None:
                norm_referer = _normalize_origin(raw_referer, is_origin_header=False)
                if not norm_referer or norm_referer not in self.allowed_origins:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF verification failed: untrusted referer"},
                    )
            # 3. Both Origin and Referer are absent
            else:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF verification failed: missing origin and referer"},
                )

        return await call_next(request)
