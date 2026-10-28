"""Explicit schema/account administration, without default or checked-in passwords."""
import argparse
from getpass import getpass
from pathlib import Path
import re
from uuid import uuid4

import config
import database
from auth import password_hasher


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create initial PostgreSQL schema; does not delete existing data")
    create = sub.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("--role", required=True, choices=["admin", "viewer"])
    reset = sub.add_parser("reset-password")
    reset.add_argument("username")
    disable = sub.add_parser("disable-user")
    disable.add_argument("username")
    args = parser.parse_args()
    config.validate_config()
    if args.command == "init-db":
        with database.connect() as db:
            db.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        print("PostgreSQL schema v1 ready.")
        return
    username = args.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username):
        parser.error("Username must be 3–64 letters, digits, dots, underscores or hyphens")
    password = None
    if args.command != "disable-user":
        password = getpass("Password (12–256 characters): ")
        if not 12 <= len(password) <= 256 or password != getpass("Confirm password: "):
            parser.error("Passwords must match and contain 12–256 characters")
    with database.connect() as db:
        if args.command == "create-user":
            if db.execute("SELECT id FROM app_users WHERE username=%s", (username,)).fetchone():
                parser.error("Username already exists")
            row = db.execute("INSERT INTO app_users(id,username,password_hash,role) VALUES (%s,%s,%s,%s) RETURNING id",
                             (uuid4(), username, password_hasher.hash(password), args.role)).fetchone()
        else:
            row = db.execute("SELECT id FROM app_users WHERE username=%s FOR UPDATE", (username,)).fetchone()
            if not row:
                parser.error("Username does not exist")
            if args.command == "reset-password":
                db.execute("UPDATE app_users SET password_hash=%s WHERE id=%s", (password_hasher.hash(password), row["id"]))
            else:
                db.execute("UPDATE app_users SET active=false WHERE id=%s", (row["id"],))
            db.execute("DELETE FROM auth_sessions WHERE user_id=%s", (row["id"],))
        database.audit(db, "account." + args.command, row["id"])
    print("Account updated:", username)


if __name__ == "__main__":
    main()
