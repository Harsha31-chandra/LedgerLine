"""
LedgerLine — Application configuration.

All settings are loaded from environment variables (or .env file).
Never hardcode secrets. See .env.example for variable names.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://ledgerline:ledgerline_dev@localhost:5432/ledgerline"
    test_database_url: str = "postgresql://ledgerline:ledgerline_dev@localhost:5432/ledgerline_test"
    migration_database_url: str | None = None

    # Session security
    session_secret: str = "change-me-to-a-random-string"

    # Application environment
    app_env: str = "development"

    # CORS — comma-separated origins
    cors_origins: str = "http://localhost:5173"

    # Cookie security
    cookie_secure: bool = False

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
