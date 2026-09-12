"""Point-in-time snapshot of the whole system state, for business continuity.

Takes a CONSISTENT copy of the SQLite database using the SQLite online-backup API
(safe even while the server is running), together with the session signing key and
the local outbox, into a timestamped folder under ``backups/``. A ``manifest.json``
records when/what was snapshotted plus the code revision, so ``restore.py`` can warn
about code/schema drift.

    .venv/Scripts/python backup.py                 # auto label = timestamp
    .venv/Scripts/python backup.py before-q3-import

Retention (rolling): keeps the most recent N snapshots (default 20, override with
BACKUP_KEEP or --keep); older ones are moved to the recycle bin / .trash, never
hard-deleted.

The snapshot folder layout:
    backups/<ts>_<label>/
        app.db          consistent DB copy (SQLite backup API)
        secret.key      session signing key (so restored sessions stay valid)
        outbox/         local sent-letter HTML (if present)
        manifest.json   {created_at, label, git_commit, db_integrity, row_counts}
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.db import DB_PATH  # noqa: E402

DATA_DIR = DB_PATH.parent
BACKUP_DIR = ROOT / "backups"
SECRET_FILE = DATA_DIR / "secret.key"
OUTBOX_DIR = DATA_DIR / "outbox"

# Tables we care about for the manifest sanity snapshot.
TABLES = ["users", "bonus_plans", "plan_kpis", "actuals", "curves", "calc_runs",
          "bonus_results", "adjustments", "locks", "data_op_logs", "labels",
          "letter_templates", "letters"]


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001  (git missing / not a repo)
        return "unknown"


def _move_to_trash(path: Path) -> None:
    """Never hard-delete: recycle bin on Windows, .trash fallback otherwise."""
    if os.name == "nt":
        import ctypes  # best-effort; fall back to .trash on any failure
        try:
            # pFrom must be double-null-terminated per the Win32 API.
            op = _shofo(str(path.resolve()) + "\0\0")
            res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
            if res == 0:
                return
        except Exception:  # noqa: BLE001
            pass
    trash = ROOT / ".trash"
    trash.mkdir(exist_ok=True)
    dest = trash / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{path.name}"
    shutil.move(str(path), str(dest))


def _shofo(pfrom: str):
    import ctypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", ctypes.c_bool),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
    # FO_DELETE=0; FOF_ALLOWUNDO=0x40, FOF_NOCONFIRMATION=0x10, FOF_SILENT=0x4
    return SHFILEOPSTRUCTW(None, 0, pfrom, None, 0x40 | 0x10 | 0x4, False, None, None)


def _row_counts(db_file: Path) -> dict:
    try:
        con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        cur = con.cursor()
        counts = {}
        for tbl in TABLES:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                counts[tbl] = cur.fetchone()[0]
            except sqlite3.Error:
                counts[tbl] = None
        con.close()
        return counts
    except sqlite3.Error:
        return {}


def prune(keep: int) -> None:
    """Keep the newest `keep` snapshot folders; move the rest to trash."""
    if keep <= 0 or not BACKUP_DIR.exists():
        return
    snaps = sorted([p for p in BACKUP_DIR.iterdir()
                    if p.is_dir() and (p / "manifest.json").exists()],
                   key=lambda p: p.name, reverse=True)
    for old in snaps[keep:]:
        print(f"[backup] retention: removing old snapshot {old.name}")
        _move_to_trash(old)


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot the system to backups/")
    ap.add_argument("label", nargs="?", default="", help="optional human label")
    ap.add_argument("--keep", type=int, default=int(os.environ.get("BACKUP_KEEP", "20")),
                    help="rolling number of snapshots to retain (0 = keep all)")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"[backup] ERROR: database not found at {DB_PATH}. Run seed.py first.")
        return 2

    ts = datetime.now(timezone.utc)
    label = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (args.label or "")).strip("_")
    name = f"{ts:%Y%m%dT%H%M%SZ}" + (f"_{label}" if label else "")
    dest = BACKUP_DIR / name
    dest.mkdir(parents=True, exist_ok=False)

    # 1) consistent DB copy via the online backup API (safe while server runs)
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(dest / "app.db"))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    # integrity check of the snapshot
    con = sqlite3.connect(str(dest / "app.db"))
    integrity = con.execute("PRAGMA quick_check").fetchone()[0]
    con.close()
    if integrity != "ok":
        print(f"[backup] ERROR: snapshot failed quick_check ({integrity}); aborting.")
        _move_to_trash(dest)
        return 1

    # 2) signing key + 3) outbox
    if SECRET_FILE.exists():
        shutil.copy2(SECRET_FILE, dest / "secret.key")
    if OUTBOX_DIR.exists():
        shutil.copytree(OUTBOX_DIR, dest / "outbox")

    manifest = {
        "created_at": ts.isoformat(),
        "label": args.label or "",
        "git_commit": _git_commit(),
        "db_integrity": integrity,
        "row_counts": _row_counts(dest / "app.db"),
        "has_secret_key": SECRET_FILE.exists(),
        "has_outbox": OUTBOX_DIR.exists(),
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), "utf-8")

    print(f"[backup] snapshot created: {dest.relative_to(ROOT)}")
    print(f"[backup]   git={manifest['git_commit']}  tables={sum(1 for v in manifest['row_counts'].values() if v)}")
    print(f"[backup]   row_counts={ {k: v for k, v in manifest['row_counts'].items() if v} }")

    prune(args.keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
