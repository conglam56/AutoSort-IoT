"""Administrative account management. All writes recheck the actor under a DB lock."""
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
import psycopg

if __package__:
    from . import auth, database
else:
    import auth
    import database

router = APIRouter(prefix="/api/admin", tags=["administration"])


class CreateAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "viewer"] = "viewer"

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class EditAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "viewer"]
    active: bool = Field(strict=True)


class ResetPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=12, max_length=256)


def public_account(row):
    return {"id": str(row["id"]), "username": row["username"], "role": row["role"],
            "active": row["active"], "createdAt": row["created_at"].isoformat(),
            "activeSessions": row.get("active_sessions", 0)}


def target_account(db, user_id):
    row = db.execute("SELECT * FROM app_users WHERE id=%s FOR UPDATE", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "ACCOUNT_NOT_FOUND")
    return row


@router.get("/users")
def list_users(search: str = Query("", max_length=64), limit: int = Query(25, ge=1, le=100),
               offset: int = Query(0, ge=0), user=Depends(auth.require_admin_read)):
    with database.connect() as db:
        total = db.execute("SELECT count(*) AS n FROM app_users WHERE position(%s in username)>0", (search.strip().lower(),)).fetchone()["n"]
        rows = db.execute("""SELECT u.*, (SELECT count(*) FROM auth_sessions s WHERE s.user_id=u.id AND s.expires_at>now()) AS active_sessions
                             FROM app_users u WHERE position(%s in username)>0 ORDER BY u.created_at,u.id LIMIT %s OFFSET %s""",
                          (search.strip().lower(), limit, offset)).fetchall()
    return {"users": [public_account(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/users", status_code=201)
def create_user(body: CreateAccount, request: Request, user=Depends(auth.require_admin)):
    hashed = auth.password_hasher.hash(body.password)
    try:
        with database.connect() as db:
            auth.lock_authenticated_user(db, user, admin=True)
            row = db.execute("INSERT INTO app_users(id,username,password_hash,role) VALUES (%s,%s,%s,%s) RETURNING *",
                             (uuid4(), body.username, hashed, body.role)).fetchone()
            database.audit(db, "account.created:" + body.username, user["id"], auth.client_ip(request))
            return public_account(row)
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(409, "USERNAME_EXISTS") from error


@router.post("/users/{user_id}/settings")
def edit_user(user_id: UUID, body: EditAccount, request: Request, user=Depends(auth.require_admin)):
    with database.connect() as db:
        auth.lock_authenticated_user(db, user, admin=True)
        target = target_account(db, user_id)
        if target["role"] == "admin" and target["active"] and (body.role != "admin" or not body.active):
            other = db.execute("SELECT id FROM app_users WHERE active AND role='admin' AND id<>%s LIMIT 1", (user_id,)).fetchone()
            if not other:
                raise HTTPException(409, "LAST_ADMIN_REQUIRED")
        if user_id == user["id"] and (body.role != target["role"] or body.active != target["active"]):
            raise HTTPException(409, "CANNOT_CHANGE_OWN_ACCESS")
        if body.role != target["role"] or body.active != target["active"]:
            db.execute("UPDATE app_users SET role=%s,active=%s WHERE id=%s", (body.role, body.active, user_id))
            db.execute("DELETE FROM auth_sessions WHERE user_id=%s", (user_id,))
            if body.role != target["role"]:
                database.audit(db, "account.role_changed:" + target["username"], user["id"], auth.client_ip(request))
            if body.active != target["active"]:
                database.audit(db, ("account.enabled:" if body.active else "account.disabled:") + target["username"], user["id"], auth.client_ip(request))
        return {"ok": True}


@router.post("/users/{user_id}/password")
def reset_password(user_id: UUID, body: ResetPassword, request: Request, user=Depends(auth.require_admin)):
    if user_id == user["id"]:
        raise HTTPException(409, "USE_OWN_PASSWORD_FORM")
    hashed = auth.password_hasher.hash(body.password)
    with database.connect() as db:
        auth.lock_authenticated_user(db, user, admin=True)
        target = target_account(db, user_id)
        db.execute("UPDATE app_users SET password_hash=%s WHERE id=%s", (hashed, user_id))
        db.execute("DELETE FROM auth_sessions WHERE user_id=%s", (user_id,))
        database.audit(db, "account.password_reset:" + target["username"], user["id"], auth.client_ip(request))
    return {"ok": True}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(user_id: UUID, request: Request, user=Depends(auth.require_admin)):
    if user_id == user["id"]:
        raise HTTPException(409, "USE_LOGOUT")
    with database.connect() as db:
        auth.lock_authenticated_user(db, user, admin=True)
        target = target_account(db, user_id)
        db.execute("DELETE FROM auth_sessions WHERE user_id=%s", (user_id,))
        database.audit(db, "account.sessions_revoked:" + target["username"], user["id"], auth.client_ip(request))
    return {"ok": True}


@router.get("/audit-logs")
def list_audit_logs(kind: Literal["all", "login", "account", "session"] = "all",
                    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                    user=Depends(auth.require_admin_read)):
    prefix = "" if kind == "all" else kind + "."
    with database.connect() as db:
        total = db.execute("SELECT count(*) AS n FROM audit_logs WHERE starts_with(action,%s) OR (%s='login' AND action='logout')", (prefix, kind)).fetchone()["n"]
        rows = db.execute("""SELECT a.id,a.action,a.ip_address,a.created_at,u.username FROM audit_logs a
                             LEFT JOIN app_users u ON u.id=a.user_id WHERE starts_with(a.action,%s) OR (%s='login' AND a.action='logout')
                             ORDER BY a.id DESC LIMIT %s OFFSET %s""", (prefix, kind, limit, offset)).fetchall()
    return {"logs": rows, "total": total, "limit": limit, "offset": offset}
