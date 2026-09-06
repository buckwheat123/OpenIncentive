from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .i18n import Translator, get_lang

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["fmt"] = lambda dt: dt.strftime("%Y-%m-%d %H:%M") if dt else ""
templates.env.filters["num"] = lambda v: f"{v:,.2f}" if isinstance(v, (int, float)) else v


def _g(v):
    """Compact number without scientific notation (large currency values stay readable)."""
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f.is_integer() else f"{f:.4f}".rstrip("0").rstrip(".")
    return v


templates.env.filters["g"] = _g


def _proxy_admin(request: Request):
    """Original platform admin behind a proxy session (for the banner), else None."""
    from .db import SessionLocal
    from .deps import session_payload
    from .models import User

    payload = session_payload(request)
    if not payload or not payload.get("p"):
        return None
    db = SessionLocal()
    try:
        return db.get(User, payload["p"])
    finally:
        db.close()


def render(request: Request, name: str, **context):
    lang = get_lang(request)
    tr = Translator(lang)
    context.setdefault("t", tr.t)
    context.setdefault("tl", tr.tl)
    context.setdefault("lang", lang)
    context.setdefault("proxy_admin", _proxy_admin(request))
    return templates.TemplateResponse(request, name, context)
