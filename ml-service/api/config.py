"""
Configuration settings for FastAPI ML service.
Loads from environment variables and .env file.

SECURITY NOTE: API_KEY has no default value and MUST be supplied via the
.env file or the API_KEY environment variable.  The service will refuse to
start if the variable is missing or left blank.
"""

from pathlib import Path
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # No default — must be set in .env or environment.  Startup fails if absent.
    API_KEY: str
    ENVIRONMENT: str = "development"
    HOST: str = "127.0.0.1"
    PORT: int = 8001
    CORS_ORIGINS: List[str] = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
    ]

    DATA_DIR: Path = BASE_DIR / "data"
    MODELS_DIR: Path = BASE_DIR / "models" / "saved"
    METRICS_FILE: Path = BASE_DIR / "models" / "metrics.json"
    BATCH_RESULTS_DIR: Path = BASE_DIR / "reports" / "batch_predictions"

    DEFAULT_BUSINESS_ID: str = "biz_001"

    # Comma-separated list of business IDs this API key is permitted to access.
    # E.g. in .env: ALLOWED_BUSINESS_IDS=biz_001,biz_002
    # Leave empty to allow any business_id (single-tenant / dev mode only).
    # Stored as a plain string and split on access to avoid pydantic-settings
    # JSON-parsing a comma-separated value.
    ALLOWED_BUSINESS_IDS: str = ""

    @property
    def allowed_business_ids_list(self) -> List[str]:
        """Returns ALLOWED_BUSINESS_IDS as a list, splitting on commas."""
        return [b.strip() for b in self.ALLOWED_BUSINESS_IDS.split(",") if b.strip()]

    @field_validator("ALLOWED_BUSINESS_IDS", mode="before")
    @classmethod
    def parse_business_ids(cls, v: object) -> str:
        """Accept either a string or a list and normalise to comma-separated string."""
        if isinstance(v, list):
            return ",".join(str(i).strip() for i in v if str(i).strip())
        return str(v) if v is not None else ""

    @field_validator("API_KEY")
    @classmethod
    def api_key_must_be_strong(cls, v: str) -> str:
        """Reject blank values and the well-known insecure development default."""
        _INSECURE_DEFAULTS = {
            "dev-secret-key-food-waste-2026",
            "changeme",
            "secret",
            "password",
        }
        if not v or not v.strip():
            raise ValueError(
                "API_KEY must not be empty. Set it in .env or the API_KEY environment variable."
            )
        if v.strip().lower() in _INSECURE_DEFAULTS:
            raise ValueError(
                f"API_KEY '{v}' is a known insecure default. "
                "Please set a strong, random secret in your .env file."
            )
        return v

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
settings.BATCH_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
