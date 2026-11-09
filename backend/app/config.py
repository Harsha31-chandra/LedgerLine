"""
LedgerLine — Application configuration.

All settings are loaded from environment variables (or .env file).
Never hardcode secrets. See .env.example for variable names.
"""

from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://ledgerline:ledgerline_dev@localhost:5432/ledgerline"
    test_database_url: str = "postgresql://ledgerline:ledgerline_dev@localhost:5432/ledgerline_test"
    migration_database_url: str | None = None

    # Session security
    session_secret: str = "change-me-to-a-random-string"
    session_cookie_name: str = "ledgerline_session"
    session_ttl_minutes: int = 1440  # Default 24 hours fixed session expiry

    # Rate limiting (configurable SlowAPI limits)
    rate_limit_register: str = "5/minute"
    rate_limit_login: str = "10/minute"

    # Application environment
    app_env: str = "development"

    # CORS & CSRF — comma-separated explicitly trusted origins
    cors_origins: str = "http://localhost:5173,http://localhost:8000,http://127.0.0.1:8000,http://[::1]:8000"

    # Cookie security
    cookie_secure: bool = False

    @field_validator("session_ttl_minutes", mode="before")
    @classmethod
    def validate_session_ttl_minutes(cls, v: Any) -> int:
        """Ensure session time-to-live is a strictly positive integer.

        Explicitly rejects booleans (e.g. True/False), floats (e.g. 14.0/14.5),
        zero, negative values, and non-numeric types. Valid positive integers and
        valid integer strings (loaded from environment variables) are accepted.
        """
        if isinstance(v, bool):
            raise ValueError("session_ttl_minutes cannot be a boolean")
        if isinstance(v, float):
            raise ValueError("session_ttl_minutes cannot be a float")
        if isinstance(v, int):
            if v <= 0:
                raise ValueError("session_ttl_minutes must be a positive integer greater than zero")
            return v
        if isinstance(v, str):
            cleaned = v.strip()
            if not cleaned.isdigit():
                raise ValueError("session_ttl_minutes must be a valid positive integer string")
            val = int(cleaned)
            if val <= 0:
                raise ValueError("session_ttl_minutes must be a positive integer greater than zero")
            return val
        raise ValueError("session_ttl_minutes must be a positive integer")

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Fail closed if production environment attempts to run with insecure default secrets."""
        is_production = (self.app_env or "").strip().lower() in ("production", "prod")
        insecure_placeholders = {
            "change-me-to-a-random-string",
            "changeme",
            "secret",
            "",
        }
        if is_production:
            secret = (self.session_secret or "").strip()
            if not secret or secret in insecure_placeholders or len(secret) < 32:
                raise ValueError(
                    "Insecure production configuration: 'session_secret' must be a secure random secret "
                    "of at least 32 characters in production environments. Known placeholder values are rejected."
                )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


settings = Settings()
