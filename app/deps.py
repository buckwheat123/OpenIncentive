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


def make_session(user_id: int) -> str:
    return _serializer.dumps(user_id)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        user_id = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.get(User, user_id)
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
