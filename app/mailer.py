"""Mailer: real SMTP when configured, otherwise a local outbox folder (dev/demo mode).

v5.0 — supports implicit-TLS SMTPS (e.g. 163/`smtp.163.com:465`) as well as the
classic STARTTLS path (`SMTP_USE_TLS=1`), plus a POP3 self-test used by the admin
"test connection" action. Credentials are NEVER hard-coded: they are read from the
process environment, optionally seeded from a git-ignored ``.env`` file at the repo
root (see ``load_env_file``). ``.env`` is excluded from git by ``.gitignore``.

163 setup recap (documentation only, secrets live in .env):
    SMTP_HOST=smtp.163.com
    SMTP_PORT=465
    SMTP_USE_SSL=1          # implicit TLS; mutually exclusive with SMTP_USE_TLS
    SMTP_USER=you@example.com
    SMTP_PASSWORD=<授权码>   # the 163 "client auth code", NOT the login password
    POP3_HOST=pop.163.com
    POP3_PORT=995
    POP3_USE_SSL=1
"""

import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

OUTBOX_DIR = Path(__file__).resolve().parent.parent / "data" / "outbox"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file(path: Path | None = None) -> None:
    """Populate os.environ from a KEY=VALUE .env file without overwriting real env.

    Called defensively from send_mail/test_connection so the app works whether or
    not it was launched through run.py. Missing file is not an error.
    """
    env_path = path or ENV_FILE
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _disabled() -> bool:
    """Explicit kill-switch for automated tests / offline demos: when ``SMTP_DISABLED=1``
    is present in the environment every network path is bypassed and the mailer behaves
    exactly like an unconfigured (outbox-only) install, even if a real ``.env`` exists."""
    return os.environ.get("SMTP_DISABLED", "").strip() == "1"


def _config() -> dict:
    load_env_file()
    cfg = {
        "host": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", "465")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "sender": os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "bonus-platform@example.com")),
        "use_ssl": os.environ.get("SMTP_USE_SSL", "0") == "1",
        "use_tls": os.environ.get("SMTP_USE_TLS", "1") == "1",
    }
    if _disabled():
        cfg["host"] = None
    return cfg


def smtp_enabled() -> bool:
    return bool(_config()["host"])


def _deliver(cfg: dict, to_email: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["To"] = to_email
    msg["From"] = cfg["sender"]
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html", "utf-8"))
    if cfg["use_ssl"]:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30) as server:
            if cfg["user"]:
                server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            if cfg["use_tls"]:
                server.starttls()
            if cfg["user"]:
                server.login(cfg["user"], cfg["password"])
            server.send_message(msg)


def send_mail(to_email: str, subject: str, html: str) -> str:
    """Send and return the mode used: 'smtp' or 'outbox'.

    Falls back to the local outbox folder when SMTP_HOST is not configured so the
    demo/seeded environment never tries to hit the network.
    """
    cfg = _config()
    if cfg["host"]:
        _deliver(cfg, to_email, subject, html)
        return "smtp"
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    safe_addr = to_email.replace("@", "_at_")
    path = OUTBOX_DIR / f"{stamp}_{safe_addr}.html"
    path.write_text(f"<!-- To: {to_email}\n     Subject: {subject} -->\n{html}", encoding="utf-8")
    return "outbox"


def test_smtp() -> dict:
    """Log in to the configured SMTP server (no message sent) and report the result."""
    cfg = _config()
    if not cfg["host"]:
        return {"ok": False, "transport": "smtp", "detail": "SMTP_HOST 未配置（当前为本地 outbox 模式）"}
    try:
        if cfg["use_ssl"]:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
            if cfg["use_tls"]:
                server.starttls()
        with server:
            if cfg["user"]:
                server.login(cfg["user"], cfg["password"])
        return {"ok": True, "transport": "smtp",
                "detail": f"SMTP 登录成功：{cfg['host']}:{cfg['port']}（{cfg['user']}）"}
    except Exception as exc:  # noqa: BLE001 - surface any transport error to the admin
        return {"ok": False, "transport": "smtp", "detail": f"SMTP 登录失败：{exc}"}


def test_pop3() -> dict:
    """Connect + log in to the configured POP3 server and report inbox count."""
    import poplib

    load_env_file()
    host = os.environ.get("POP3_HOST")
    if not host:
        return {"ok": False, "transport": "pop3", "detail": "POP3_HOST 未配置"}
    port = int(os.environ.get("POP3_PORT", "995"))
    user = os.environ.get("SMTP_USER") or os.environ.get("POP3_USER")
    password = os.environ.get("SMTP_PASSWORD") or os.environ.get("POP3_PASSWORD")
    try:
        if os.environ.get("POP3_USE_SSL", "1") == "1":
            conn = poplib.POP3_SSL(host, port, timeout=30)
        else:
            conn = poplib.POP3(host, port, timeout=30)
        try:
            conn.user(user)
            conn.pass_(password)
            count, _size = conn.stat()
        finally:
            conn.quit()
        return {"ok": True, "transport": "pop3",
                "detail": f"POP3 登录成功：{host}:{port}（{user}），收件箱 {count} 封"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "transport": "pop3", "detail": f"POP3 登录失败：{exc}"}


def test_connection() -> list[dict]:
    """Run every configured transport self-test the admin can act on."""
    if _disabled():
        return [{"ok": True, "transport": "outbox",
                 "detail": "SMTP_DISABLED=1：本地 outbox 模式，跳过联网测试（SMTP/POP3）"}]
    results = [test_smtp()]
    if os.environ.get("POP3_HOST") or (ENV_FILE.exists()):
        results.append(test_pop3())
    return results
