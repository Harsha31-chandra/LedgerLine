"""
Authentication and session request/response schemas for LedgerLine.

Defines Pydantic schemas for public user registration, credential login,
user profile responses, and session status views.

SECURITY POLICIES:
- Plaintext passwords are accepted only on registration and login input schemas.
- Passwords are never echoed or included in any response schema.
- Sensitive internal hashes (password_hash, session token_hash) are strictly excluded.
- UserRegisterRequest forbids extra fields (extra='forbid'), ensuring public registration
  cannot specify or override roles ('ADMIN', 'AUDITOR'). Public registration defaults to
  UserRole.HOLDER server-side.
- Email is normalized (stripped and lowercased) and validated against standard format.
- Password input boundaries: Enforces safe input length boundaries (non-empty string up to 128 characters).
  No arbitrary minimum length or complexity rules are invented here; the hashing layer enforces that
  passwords cannot be empty. A formal password policy (e.g. minimum length, character variety, dictionary
  blocklists) remains a separate future requirement.
"""

from datetime import datetime
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Pragmatic basic email format validation pattern (note: this is a practical format check,
# not a full RFC 5322 specification parser).
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class UserRegisterRequest(BaseModel):
    """Public account registration payload.

    Strictly forbids client assignment of roles; all public registrations
    are assigned UserRole.HOLDER by the server.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="User email address (normalized to lowercase).",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Plaintext password (non-empty string, maximum 128 characters).",
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full legal or display name of the account holder.",
    )

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        """Validate and lowercase normalize email address."""
        if not isinstance(v, str):
            raise ValueError("Email must be a string")
        cleaned = v.strip().lower()
        if not cleaned or not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email address format")
        return cleaned

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        """Validate non-empty full name after stripping whitespace."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Full name cannot be empty or whitespace only")
        return cleaned


class UserLoginRequest(BaseModel):
    """User login credential payload."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="User email address.",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Account password.",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize login email address to lowercase."""
        if not isinstance(v, str):
            raise ValueError("Email must be a string")
        cleaned = v.strip().lower()
        if not cleaned or not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email address format")
        return cleaned


class UserResponse(BaseModel):
    """Public user profile response schema (excludes password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SessionResponse(BaseModel):
    """Public session view (excludes internal token_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None
    last_activity_at: datetime | None = None
