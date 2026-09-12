"""Session auth & role-based access dependencies."""

from pathlib import Path

from fastapi import Depends, HTTPException, Request
from itsdangerous import URLSafeTimedSerializer
from itsdangerous.exc import BadSignature, SignatureExpired
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import DATA_DIR, SessionLocal
from .models import User, UserManagedBg, UserVersion, utcnow

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


# ---------- BG scope helpers (feature #4: a BG_ADMIN may manage multiple BGs) ----------

def bg_filter(user: User) -> set[str] | None:
    """BGs an acting user may touch. None = unrestricted (platform ADMIN sees all)."""
    if user.role == "ADMIN":
        return None
    if user.role == "BG_ADMIN":
        return user.bg_scope
    return {user.bg} if user.bg else set()


def bg_allowed(user: User, emp_bg: str | None) -> bool:
    """Whether an employee's BG falls inside the acting user's scope."""
    scope = bg_filter(user)
    return True if scope is None else (emp_bg in scope)


def apply_managed_bgs(db: Session, user: User, bgs: list[str]) -> None:
    """Sync a BG_ADMIN's administered BGs to the given list (ordered, de-duplicated)
    WITHOUT committing, so callers can fold it into a larger transaction. Keeps User.bg
    as the primary (first) managed BG."""
    wanted = [b.strip() for b in bgs if b and b.strip()]
    ordered: list[str] = []
    for b in wanted:
        if b not in ordered:
            ordered.append(b)
    current = {m.bg: m for m in user.managed_bgs}
    for b in ordered:
        if b not in current:
            db.add(UserManagedBg(user_id=user.id, bg=b))
    for b, row in current.items():
        if b not in ordered:
            db.delete(row)
    if user.role == "BG_ADMIN":
        user.bg = ordered[0] if ordered else None


def set_managed_bgs(db: Session, user: User, bgs: list[str]) -> None:
    """Idempotently sync a BG_ADMIN's administered BGs, committing the change."""
    apply_managed_bgs(db, user, bgs)
    db.commit()


def current_info_tuple(user: User) -> tuple:
    """Comparable snapshot of the mutable identity fields on the live user."""
    return (user.name, user.email, user.role, user.bg or "", user.department or "",
            user.job_title or "", user.manager_id)


def archive_user_info(db: Session, user: User, actor: User | None) -> UserVersion:
    """Feature #4: before a user's info changes, archive the current (superseded)
    attribute set as an inactive UserVersion row (旧信息停用封存). Callers apply the new
    values to `user` afterwards (新信息启用). Not committed here so it can join the
    caller's transaction."""
    highest = max((v.version for v in user_versions(db, user)), default=0)
    snap = UserVersion(
        user_id=user.id, version=highest + 1, name=user.name, email=user.email,
        role=user.role, bg=user.bg, department=user.department, job_title=user.job_title,
        manager_id=user.manager_id, is_active=False,
        changed_by=actor.id if actor else None, ended_at=utcnow(),
    )
    db.add(snap)
    return snap


def user_versions(db: Session, user: User) -> list[UserVersion]:
    return (db.query(UserVersion).filter(UserVersion.user_id == user.id)
            .order_by(UserVersion.version.desc()).all())
