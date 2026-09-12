"""Reset to a BLANK system for manual from-scratch testing.

Deletes data/app.db, recreates empty tables, and inserts a single platform
ADMIN so you can log in. Everything else (curves, users, big-table imports,
calculation runs) you create by hand in the UI.

    taskkill //F //IM python.exe          # stop the server first (Windows)
    .venv/Scripts/python reset_empty.py
    .venv/Scripts/python run.py

Override the credentials via env vars if you like:
    ADMIN_ID / ADMIN_NAME / ADMIN_EMAIL / ADMIN_PW
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import DB_PATH, SessionLocal, init_db  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    emp_id = os.environ.get("ADMIN_ID", "ADMIN1")
    name = os.environ.get("ADMIN_NAME", "平台管理员")
    email = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    pw = os.environ.get("ADMIN_PW", emp_id)  # default: password = employee id

    db = SessionLocal()
    db.add(User(employee_id=emp_id, name=name, email=email, bg=None,
                department=None, job_title=None, role="ADMIN",
                password_hash=hash_password(pw)))
    db.commit()
    db.close()

    print(f"[reset_empty] database rebuilt at {DB_PATH}")
    print(f"[reset_empty] one ADMIN created -> login: {emp_id} / {pw}")
    print("[reset_empty] all other data is empty; build it manually in the UI.")


if __name__ == "__main__":
    main()
