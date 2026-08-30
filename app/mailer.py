"""Mailer: real SMTP when configured, otherwise a local outbox folder (dev/demo mode)."""

import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

OUTBOX_DIR = Path(__file__).resolve().parent.parent / "data" / "outbox"


def send_mail(to_email: str, subject: str, html: str) -> str:
    """Send and return the mode used: 'smtp' or 'outbox'."""
    host = os.environ.get("SMTP_HOST")
    if host:
        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["From"] = os.environ.get("SMTP_FROM", "bonus-platform@example.com")
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as server:
            if os.environ.get("SMTP_USE_TLS", "1") == "1":
                server.starttls()
            user = os.environ.get("SMTP_USER")
            if user:
                server.login(user, os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg)
        return "smtp"
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    safe_addr = to_email.replace("@", "_at_")
    path = OUTBOX_DIR / f"{stamp}_{safe_addr}.html"
    path.write_text(f"<!-- To: {to_email}\n     Subject: {subject} -->\n{html}", encoding="utf-8")
    return "outbox"
