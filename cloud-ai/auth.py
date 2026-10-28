"""Cookie sessions for people, a separate API key for Camera Bridge."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from pwdlib import PasswordHash

if __package__:
    from . import config, database
else:
    import config
    import database

router = APIRouter(prefix="/api/auth", tags=["authentication"])
password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))
device_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="CameraBridgeKey")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def client_ip(request):
    # Trust proxy headers only when uvicorn's trusted forwarded IPs are configured.
    return request.client.host if request.client else "unknown"


def require_origin(request: Request):
    if request.headers.get("origin", "").rstrip("/") not in config.ALLOWED_ORIGINS:
        raise HTTPException(403, "Dashboard origin not allowed")


def current_user(request: Request):
    token = request.cookies.get(config.COOKIE_NAME, "")
    if not token or len(token) > 256:
        raise HTTPException(401, "Login required")
    with database.connect() as db:
        user = db.execute("""SELECT u.id,u.username,u.role,s.csrf_token,s.token_hash,s.expires_at
                             FROM auth_sessions s JOIN app_users u ON u.id=s.user_id
                             WHERE s.token_hash=%s AND s.expires_at>now() AND u.active""", (digest(token),)).fetchone()
    if not user:
        raise HTTPException(401, "Session expired. Please log in again")
    return user


def require_csrf(request: Request, user=Depends(current_user)):
    require_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not secrets.compare_digest(supplied.encode(), user["csrf_token"].encode()):
        raise HTTPException(403, "CSRF token invalid")
    return user


def require_admin(user=Depends(require_csrf)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator permission required")
    return user


def require_admin_read(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator permission required")
    return user


def require_device(api_key: str | None = Security(device_header)):
    supplied = api_key or ""
    if not config.DEVICE_API_KEY or not secrets.compare_digest(digest(supplied), digest(config.DEVICE_API_KEY)):
        raise HTTPException(401, "Invalid device API key")


def public_user(user):
    return {"username": user["username"], "role": user["role"], "csrfToken": user["csrf_token"],
            "expiresAt": user["expires_at"].isoformat()}


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def consume_login_attempt(ip, username):
    limited = False
    # Separate limits resist username rotation and repeated distributed guesses.
    buckets = [("ip:" + digest(ip), 30), ("user:" + digest(username), 10)]
    with database.connect() as db:
        db.execute("DELETE FROM login_limits WHERE window_start < now()-interval '1 day'")
        for bucket, maximum in sorted(buckets):
            row = db.execute("""INSERT INTO login_limits(bucket,attempts) VALUES (%s,1)
                ON CONFLICT(bucket) DO UPDATE SET
                attempts=CASE WHEN login_limits.window_start < now()-interval '15 minutes' THEN 1 ELSE login_limits.attempts+1 END,
                window_start=CASE WHEN login_limits.window_start < now()-interval '15 minutes' THEN now() ELSE login_limits.window_start END
                RETURNING attempts""", (bucket,)).fetchone()
            limited |= row["attempts"] > maximum
    if limited:
        raise HTTPException(429, "Too many login attempts. Try again in 15 minutes", headers={"Retry-After": "900"})


@router.post("/login", dependencies=[Depends(require_origin)])
def login(body: LoginBody, request: Request, response: Response):
    username = body.username.strip().lower()
    ip = client_ip(request)
    consume_login_attempt(ip, username)
    with database.connect() as db:
        user = db.execute("SELECT * FROM app_users WHERE username=%s", (username,)).fetchone()
    valid = password_hasher.verify(body.password, user["password_hash"] if user else dummy_hash)
    if not user or not valid or not user["active"]:
        with database.connect() as db:
            database.audit(db, "login.failed", ip=ip)
        raise HTTPException(401, "Invalid username or password")

    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=config.SESSION_HOURS)
    with database.connect() as db:
        # Rotate an existing browser session when switching users or logging in again.
        db.execute("DELETE FROM auth_sessions WHERE expires_at<=now() OR token_hash=%s",
                   (digest(request.cookies.get(config.COOKIE_NAME, "")),))
        db.execute("INSERT INTO auth_sessions(token_hash,user_id,csrf_token,expires_at) VALUES (%s,%s,%s,%s)",
                   (digest(token), user["id"], csrf, expires))
        database.audit(db, "login.succeeded", user["id"], ip)
    response.set_cookie(config.COOKIE_NAME, token, max_age=config.SESSION_HOURS*3600,
                        httponly=True, secure=config.COOKIE_SECURE, samesite="lax", path="/")
    return public_user({**user, "csrf_token": csrf, "expires_at": expires})


@router.get("/me")
def me(user=Depends(current_user)):
    return public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(require_csrf)):
    with database.connect() as db:
        db.execute("DELETE FROM auth_sessions WHERE token_hash=%s", (user["token_hash"],))
        database.audit(db, "logout", user["id"], client_ip(request))
    response.delete_cookie(config.COOKIE_NAME, path="/", httponly=True,
                           secure=config.COOKIE_SECURE, samesite="lax")
    return {"ok": True}
