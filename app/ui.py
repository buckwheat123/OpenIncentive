from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .i18n import Translator, get_lang

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["fmt"] = lambda dt: dt.strftime("%Y-%m-%d %H:%M") if dt else ""
templates.env.filters["num"] = lambda v: f"{v:,.2f}" if isinstance(v, (int, float)) else v
templates.env.filters["g"] = lambda v: f"{v:g}" if isinstance(v, (int, float)) else v


def render(request: Request, name: str, **context):
    lang = get_lang(request)
    tr = Translator(lang)
    context.setdefault("t", tr.t)
    context.setdefault("tl", tr.tl)
    context.setdefault("lang", lang)
    return templates.TemplateResponse(request, name, context)
