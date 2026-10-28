"""Environment configuration. Secrets never belong in source control."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
DATABASE_SSLMODE = os.getenv("DATABASE_SSLMODE", "")
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_NAME = "autosort_session"
SESSION_HOURS = 8
def read_allowed_origins():
    default = os.getenv("RENDER_EXTERNAL_URL", "") if os.getenv("RENDER") == "true" else "http://127.0.0.1:8000,http://localhost:8000"
    return [v.strip().rstrip("/") for v in os.getenv("ALLOWED_ORIGINS", default).split(",") if v.strip()]


ALLOWED_ORIGINS = read_allowed_origins()


class ConfigurationError(RuntimeError):
    """A diagnostic message written by us, containing names rather than secret values."""


def validate_config():
    if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
        raise ConfigurationError("Set DATABASE_URL to a PostgreSQL connection URL (postgresql:// or postgres://)")
    if len(DEVICE_API_KEY) < 32 or DEVICE_API_KEY.startswith("replace_"):
        raise ConfigurationError("Set DEVICE_API_KEY to a random secret of at least 32 characters")
    if not ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS:
        raise ConfigurationError("ALLOWED_ORIGINS must contain explicit dashboard origins")
    if os.getenv("RENDER") == "true" and (not COOKIE_SECURE or any(not v.startswith("https://") for v in ALLOWED_ORIGINS)):
        raise ConfigurationError("Render deployment requires COOKIE_SECURE=true and HTTPS origins")
    if not COOKIE_SECURE and any(not v.startswith(("http://127.0.0.1:", "http://localhost:")) for v in ALLOWED_ORIGINS):
        raise ConfigurationError("COOKIE_SECURE=false is only allowed for localhost development")
