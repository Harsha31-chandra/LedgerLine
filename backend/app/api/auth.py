"""
Authentication and session management API endpoints for LedgerLine.

Provides:
- POST /auth/register: Public account registration (assigns HOLDER role).
- POST /auth/login: Credential authentication and secure session cookie issuance.
- POST /auth/logout: Revocation of active session and clearing of session cookie.
- GET /auth/me: Retrieve currently authenticated user profile.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as DbSession

from backend.app.api.deps import get_current_user, get_db
from backend.app.config import settings
from backend.app.core.exceptions import (
    AuthenticationError,
    InactiveUserError,
    SessionNotFoundError,
    UserAlreadyExistsError,
)
from backend.app.core.rate_limit import limiter
from backend.app.models.user import User
from backend.app.schemas.auth import (
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from backend.app.services.auth_service import (
    authenticate_user,
    create_session,
    register_user,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account holder",
)
@limiter.limit(settings.rate_limit_register)
def register(
    request: Request,
    payload: UserRegisterRequest,
    db: Annotated[DbSession, Depends(get_db)],
) -> User:
    """Register a new user account with secure Argon2id password hashing.

    Public registration strictly assigns UserRole.HOLDER server-side.
    Returns safe user response without internal hashes or credentials.
    """
    try:
        user = register_user(
            db=db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
        )
        return user
    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/login",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user and issue session cookie",
)
@limiter.limit(settings.rate_limit_login)
def login(
    request: Request,
    response: Response,
    payload: UserLoginRequest,
    db: Annotated[DbSession, Depends(get_db)],
) -> User:
    """Authenticate user credentials and issue an HTTP-only session cookie.

    The 256-bit CSPRNG raw token is transmitted strictly via the Set-Cookie header
    with HttpOnly and SameSite=Lax attributes. The database persists only the SHA-256
    hash. The token is never returned in response JSON or logged.
    """
    try:
        user = authenticate_user(
            db=db,
            email=payload.email,
            password=payload.password,
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    except InactiveUserError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Issue server-side session
    session_res = create_session(db=db, user=user)

    # Set secure HTTP-only session cookie
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_res.raw_token,
        max_age=settings.session_ttl_minutes * 60,
        expires=settings.session_ttl_minutes * 60,
        path="/",
        domain=None,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )

    return user


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Revoke active session and clear cookie",
)
def logout(
    request: Request,
    response: Response,
    db: Annotated[DbSession, Depends(get_db)],
) -> dict[str, str]:
    """Revoke the current session in the database and clear the session cookie.

    Logout is idempotent: missing, invalid, or already revoked sessions safely
    clear the cookie and return HTTP 200 without raising server errors.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        try:
            revoke_session(db=db, raw_token=token)
        except SessionNotFoundError:
            # Idempotent logout: ignore unknown or already removed sessions
            pass

    # Clear cookie using identical path, security, and SameSite attributes
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        domain=None,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )

    return {"detail": "Successfully logged out"}


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get authenticated user profile",
)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the profile of the currently authenticated user.

    Validates session token, expiration, revocation, and active user status.
    """
    return current_user
