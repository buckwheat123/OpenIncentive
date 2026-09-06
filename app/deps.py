"""Session auth & role-based access dependencies."""

from pathlib import Path

from fastapi import Depends, HTTPException, Request
from itsdangerous import URLSafeTimedSerializer
from itsdangerous.exc import BadSignature, SignatureExpired
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import DATA_DIR, SessionLocal
from .models import User

SESSION_COOKIE = "bonus_session"
SESSION_MAX_AGE = 12 * 3600

_key_file = DATA_DIR / "secret.key"
if not _key_file.exists():
    import secrets

    _key_file.write_text(secrets.token_hex(32), encoding="utf-8")
_serializer = URLSafeTimedSerializer(_key_file.read_text(encoding="utf-8"))


def make_session(user_id: int, proxy_of: int | None = None) -> str:
    payload: dict = {"u": user_id}
    if proxy_of:
        payload["p"] = proxy_of
    return _serializer.dumps(payload)


def session_payload(request: Request) -> dict | None:
    """Parse the session cookie. Returns {"u": user_id, "p"?: original admin id}."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if isinstance(data, int):  # legacy payload: bare user id
        return {"u": data}
    if isinstance(data, dict) and isinstance(data.get("u"), int):
        return data
    return None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    payload = session_payload(request)
    if payload is None:
        return None
    user = db.get(User, payload["u"])
    return user if user and user.is_active else None


def require_user(request: Request, user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=303, headers={"Location": "/"})
        return user

    return dependency


def home_for(user: User) -> str:
    return {
        "ADMIN": "/admin",
        "BG_ADMIN": "/bg",
        "MANAGER": "/team",
    }.get(user.role, "/me")
