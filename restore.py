"""One-click restore of the system to a previously snapshotted point in time.

    .venv/Scripts/python restore.py latest                 # newest snapshot
    .venv/Scripts/python restore.py 20260912T030405Z       # by timestamp
    .venv/Scripts/python restore.py before-q3-import       # by label
    .venv/Scripts/python restore.py latest --yes           # skip the confirm prompt

Safety behaviour:
  * Verifies the snapshot (manifest + PRAGMA quick_check) before touching anything.
  * ALWAYS takes an automatic "pre-restore" snapshot of the CURRENT state first, so a
    wrong restore is itself undoable.
  * Warns if the code revision differs from the snapshot's (schema drift risk, since
    this project uses create_all with no migrations) and asks to continue.
  * The running server holds the SQLite file open on Windows, so the process must be
    stopped first; this is checked and reported clearly rather than half-restoring.
"""
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import backup as bk  # noqa: E402  reuse snapshot helpers + paths
from app.db import DB_PATH  # noqa: E402


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _server_holding_db() -> bool:
    """True if app.db is locked (server running). Used to abort before half-restoring."""
    if not DB_PATH.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=rw", uri=True, timeout=0.5)
        con.execute("BEGIN IMMEDIATE")
        con.rollback()
        con.close()
        return False
    except sqlite3.OperationalError as e:
        return "locked" in str(e).lower()


def _resolve(target: str) -> Path | None:
    """Find a snapshot folder by 'latest', timestamp prefix, or label."""
    if not bk.BACKUP_DIR.exists():
        return None
    snaps = sorted([p for p in bk.BACKUP_DIR.iterdir()
                    if p.is_dir() and (p / "manifest.json").exists()],
                   key=lambda p: p.name, reverse=True)
    if not snaps:
        return None
    if target in ("latest", "", None):
        return snaps[0]
    for p in snaps:
        if p.name == target or p.name.startswith(target) or p.name.endswith("_" + target):
            return p
    # label may contain characters sanitized in the folder name
    for p in snaps:
        manifest = _manifest(p)
        if manifest and manifest.get("label") == target:
            return p
    return None


def _manifest(path: Path) -> dict | None:
    try:
        return json.loads((path / "manifest.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Restore the system from a backups/ snapshot")
    ap.add_argument("target", nargs="?", default="latest",
                    help="'latest' (default), a snapshot timestamp, or a label")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    snap = _resolve(args.target)
    if snap is None:
        print(f"[restore] ERROR: no snapshot matching '{args.target}' under {bk.BACKUP_DIR.name}/")
        existing = sorted([p.name for p in bk.BACKUP_DIR.iterdir() if p.is_dir()]) if bk.BACKUP_DIR.exists() else []
        if existing:
            print(f"[restore] available: {', '.join(existing[-10:])}")
        return 2

    manifest = _manifest(snap) or {}
    print(f"[restore] snapshot : {snap.name}")
    print(f"[restore] created  : {manifest.get('created_at', '?')}  label={manifest.get('label') or '-'}")
    print(f"[restore] row_counts: { {k: v for k, v in (manifest.get('row_counts') or {}).items() if v} }")

    snap_db = snap / "app.db"
    if not snap_db.exists():
        print("[restore] ERROR: snapshot has no app.db.")
        return 1

    # 1) verify snapshot integrity
    con = sqlite3.connect(str(snap_db))
    check = con.execute("PRAGMA quick_check").fetchone()[0]
    con.close()
    if check != "ok":
        print(f"[restore] ERROR: snapshot failed quick_check ({check}); refusing to restore.")
        return 1

    # 2) schema/code drift warning
    cur_commit = _git_commit()
    snap_commit = manifest.get("git_commit", "unknown")
    if cur_commit != snap_commit:
        print(f"[restore] NOTE: code changed since snapshot (snapshot={snap_commit}, now={cur_commit}).")
        print("[restore]       This project has no migrations; a restored DB must match the running schema.")

    # 3) server must be stopped (Windows file lock)
    if _server_holding_db():
        print("[restore] ERROR: app.db is locked — the server is running.")
        print("[restore]       stop it first:  taskkill //F //IM python.exe   then retry.")
        return 1

    if not args.yes:
        ans = input(f"[restore] Restore system to '{snap.name}'? Current data will be replaced "
                    "(a pre-restore safety snapshot is taken). type yes to continue: ").strip().lower()
        if ans not in ("y", "yes"):
            print("[restore] cancelled.")
            return 130

    # 4) automatic pre-restore safety snapshot of the CURRENT state
    if DB_PATH.exists():
        pre = datetime.now(timezone.utc)
        pre_dir = bk.BACKUP_DIR / f"{pre:%Y%m%dT%H%M%SZ}_pre-restore-before-{snap.name}"
        pre_dir.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(str(DB_PATH))
        dst = sqlite3.connect(str(pre_dir / "app.db"))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()
        if bk.SECRET_FILE.exists():
            shutil.copy2(bk.SECRET_FILE, pre_dir / "secret.key")
        (pre_dir / "manifest.json").write_text(json.dumps({
            "created_at": pre.isoformat(), "label": "pre-restore",
            "git_commit": cur_commit, "pre_restore_of": snap.name,
            "row_counts": bk._row_counts(pre_dir / "app.db"),
            "has_secret_key": bk.SECRET_FILE.exists(), "has_outbox": False,
        }, indent=2, ensure_ascii=False), "utf-8")
        print(f"[restore] safety snapshot: {pre_dir.name}")
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 5) restore DB + signing key (+ outbox) from the snapshot
    shutil.copy2(snap_db, DB_PATH)
    if (snap / "secret.key").exists():
        shutil.copy2(snap / "secret.key", bk.SECRET_FILE)
    if (snap / "outbox").exists():
        if bk.OUTBOX_DIR.exists():
            bk._move_to_trash(bk.OUTBOX_DIR)
        shutil.copytree(snap / "outbox", bk.OUTBOX_DIR)

    # 6) verify restored DB
    con = sqlite3.connect(str(DB_PATH))
    post = con.execute("PRAGMA quick_check").fetchone()[0]
    counts = {t: (con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                                 (t,)).fetchone() else None)
              for t in bk.TABLES}
    con.close()
    if post != "ok":
        print(f"[restore] ERROR: restored DB failed quick_check ({post}).")
        print(f"[restore]       roll back with:  restore.py {pre_dir.name if DB_PATH.exists() else '...'}")
        return 1

    print(f"[restore] RESTORED to {snap.name}  (integrity={post})")
    print(f"[restore] row_counts = { {k: v for k, v in counts.items() if v} }")
    print("[restore] start the server again:  .venv/Scripts/python run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
