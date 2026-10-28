"""Explicit Render entrypoint: initialize an empty DB, bootstrap once, then serve."""
import logging
import os
from pathlib import Path
import re
from uuid import uuid4

import config
import database
from auth import password_hasher

logger = logging.getLogger("autosort-deploy")


def prepare_database():
    """Idempotent initialization for Free services without a pre-deploy command."""
    config.validate_config()
    with database.connect() as db:
        # Serialize first-time schema/account setup across simultaneous starts.
        db.execute("SELECT pg_advisory_xact_lock(83417002)")
        exists = db.execute("SELECT to_regclass('schema_version') AS name").fetchone()["name"]
        if not exists:
            if os.getenv("INITIALIZE_DATABASE") != "true":
                raise RuntimeError("Run manage.py init-db or set INITIALIZE_DATABASE=true for the first deploy")
            db.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            logger.info("Initialized PostgreSQL schema v1")
        version = db.execute("SELECT version FROM schema_version WHERE version=1").fetchone()
        if not version:
            raise RuntimeError("Unsupported database schema; migration required")
        if db.execute("SELECT id FROM app_users WHERE active AND role='admin' LIMIT 1").fetchone():
            return  # Never change an existing administrator or password on restart.
        if db.execute("SELECT id FROM app_users LIMIT 1").fetchone():
            raise RuntimeError("No active admin; use manage.py to recover the existing accounts")
        username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin").strip().lower()
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
        if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username) or not 12 <= len(password) <= 256:
            raise RuntimeError("An empty database requires a valid BOOTSTRAP_ADMIN_USERNAME and a 12–256 character BOOTSTRAP_ADMIN_PASSWORD")
        user_id = uuid4()
        db.execute("INSERT INTO app_users(id,username,password_hash,role) VALUES (%s,%s,%s,'admin')",
                   (user_id, username, password_hasher.hash(password)))
        database.audit(db, "account.bootstrap", user_id, "deploy")
        logger.info("Initial administrator created; credentials are available only in the private service environment")


def main():
    import uvicorn

    try:
        prepare_database()
        port = int(os.getenv("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
    except Exception as error:
        # Connection errors may contain a DSN. Keep credentials out of build/runtime logs.
        logger.error("Deployment initialization failed (%s). Check database connectivity and deployment environment.", type(error).__name__)
        raise SystemExit(1) from None
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=1,
                app_dir=str(Path(__file__).parent), proxy_headers=True,
                forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
