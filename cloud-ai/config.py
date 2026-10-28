"""Environment configuration. Secrets never belong in source control."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_NAME = "autosort_session"
SESSION_HOURS = 8
ALLOWED_ORIGINS = [v.strip().rstrip("/") for v in os.getenv(
    "ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
).split(",") if v.strip()]


def validate_config():
    if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("Set DATABASE_URL to a PostgreSQL connection URL in cloud-ai/.env")
    if len(DEVICE_API_KEY) < 32 or DEVICE_API_KEY.startswith("replace_"):
        raise RuntimeError("Set DEVICE_API_KEY to a random secret of at least 32 characters")
    if not ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS:
        raise RuntimeError("ALLOWED_ORIGINS must contain explicit dashboard origins")
    if not COOKIE_SECURE and any(not v.startswith(("http://127.0.0.1:", "http://localhost:")) for v in ALLOWED_ORIGINS):
        raise RuntimeError("COOKIE_SECURE=false is only allowed for localhost development")
