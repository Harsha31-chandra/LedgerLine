"""
Shared FastAPI dependencies for LedgerLine.

Provides:
- get_db: Managed SQLAlchemy database session with automatic cleanup and rollback.
- get_current_session: Authenticated (Session, User) tuple verified against session cookie.
- get_current_user: Authenticated User entity for protected route handlers.
- require_global_role: Dependency factory enforcing system roles (ADMIN, HOLDER, AUDITOR).
- require_admin: Dependency enforcing UserRole.ADMIN.
- require_auditor: Dependency enforcing UserRole.AUDITOR.
- require_holder: Dependency enforcing UserRole.HOLDER.
- get_authorized_account: Dependency factory enforcing account membership, BOLA/IDOR protection,
  auditor read-only enforcement, and action permissions.
"""

from collections.abc import Callable, Iterable
from typing import Annotated
import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DbSession

from backend.app.config import settings
from backend.app.core.database import get_db
from backend.app.core.exceptions import (
    AccountNotFoundError,
    AccountStatusError,
    AuditorReadOnlyViolationError,
    InactiveUserError,
    InsufficientMembershipRoleError,
    InsufficientRoleError,
    SessionExpiredError,
    SessionNotFoundError,
    SessionRevokedError,
)
from backend.app.models.account import Account
from backend.app.models.account_membership import AccountMembership
from backend.app.models.session import Session as SessionModel
from backend.app.models.user import User, UserRole
from backend.app.services.auth_service import validate_session
from backend.app.services.authorization_service import (
    AccountAction,
    check_global_role,
    get_account_for_user,
)

__all__ = [
    "get_authorized_account",
    "get_current_session",
    "get_current_user",
    "get_db",
    "require_account_manage",
    "require_account_operate",
    "require_account_read",
    "require_admin",
    "require_auditor",
    "require_global_role",
    "require_holder",
]


def get_current_session(
    request: Request,
    db: Annotated[DbSession, Depends(get_db)],
) -> tuple[SessionModel, User]:
    """Extract and validate the session token from the configured HTTP-only cookie.

    Args:
        request: FastAPI Request containing client cookies.
        db: Active SQLAlchemy database session.

    Returns:
        Tuple of (SessionModel, User) representing the validated active session and owner.

    Raises:
        HTTPException(401): If cookie is missing, invalid, expired, or revoked.
        HTTPException(403): If the authenticated user account has been deactivated.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        session, user = validate_session(db, raw_token=token)
        return session, user
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token",
        )
    except SessionExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired",
        )
    except SessionRevokedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked",
        )
    except InactiveUserError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )


def get_current_user(
    session_and_user: Annotated[tuple[SessionModel, User], Depends(get_current_session)],
) -> User:
    """FastAPI dependency resolving the currently authenticated User entity."""
    return session_and_user[1]


def require_global_role(*allowed_roles: UserRole | str) -> Callable[[User], User]:
    """Generate a FastAPI dependency that verifies the user has one of the allowed system roles.

    Args:
        *allowed_roles: Allowed UserRole instances or strings.

    Returns:
        FastAPI dependency function returning the verified User.

    Raises:
        HTTPException(403): If user lacks required role or is inactive.
    """

    def _role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        try:
            check_global_role(current_user, allowed_roles)
            return current_user
        except InactiveUserError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        except InsufficientRoleError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role permissions",
            )

    return _role_checker


# Convenience dependencies for standard global roles
require_admin = require_global_role(UserRole.ADMIN)
require_auditor = require_global_role(UserRole.AUDITOR)
require_holder = require_global_role(UserRole.HOLDER)


def get_authorized_account(
    action: AccountAction,
) -> Callable[[uuid.UUID, User, DbSession], tuple[Account, AccountMembership]]:
    """Generate a FastAPI dependency verifying account access and membership permissions.

    Extracts `account_id` from route path parameters, looks up the account and user's
    membership, and verifies authorization according to the permission matrix.

    Policies:
    - Returns HTTP 404 if account does not exist OR if user has no membership (anti-IDOR).
    - Returns HTTP 403 if user is an AUDITOR attempting any write/operational action.
    - Returns HTTP 403 if user's membership role is insufficient (e.g. VIEWER attempting OPERATE).
    - Returns HTTP 403 if account is FROZEN/CLOSED for operational actions.
    - Returns HTTP 403 if user is inactive.

    Args:
        action: AccountAction required by the route.

    Returns:
        FastAPI dependency function returning tuple of (Account, AccountMembership).
    """

    def _account_authorizer(
        account_id: uuid.UUID,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[DbSession, Depends(get_db)],
    ) -> tuple[Account, AccountMembership]:
        try:
            return get_account_for_user(
                db=db,
                user=current_user,
                account_id=account_id,
                action=action,
            )
        except AccountNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )
        except AuditorReadOnlyViolationError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Auditor role is restricted to read-only access",
            )
        except InsufficientMembershipRoleError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this account action",
            )
        except AccountStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )
        except InactiveUserError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )

    return _account_authorizer


# Convenience dependencies for common account actions
require_account_read = get_authorized_account(AccountAction.READ)
require_account_operate = get_authorized_account(AccountAction.OPERATE)
require_account_manage = get_authorized_account(AccountAction.MANAGE_MEMBERS)
