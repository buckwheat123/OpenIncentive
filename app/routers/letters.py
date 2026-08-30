"""Notification letters: templates, compose & send, public read-acknowledgement.

Letter bodies embed per-KPI tables and a Curve table that shows, per interval,
how much attainment maps to how much payout plus the interval slope.
"""

import json
import os
import secrets

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select

from ..deps import current_user, get_db, require_user
from ..i18n import Translator, get_lang
from ..mailer import send_mail
from ..models import Letter, LetterTemplate, User
from ..ui import render
from .auth import flash
from .views import all_periods, plan_for, result_for

router = APIRouter()

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")

TABLE_STYLE = "border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse'"


def _allowed(user: User) -> bool:
    return user.role in ("BG_ADMIN", "ADMIN")


def _scope_bg(user: User) -> str | None:
    return None if user.role == "ADMIN" else user.bg


# ---------- placeholders rendering ----------

def build_plan_table(db, recipient: User, period: str, tr: Translator) -> str:
    plan = plan_for(db, recipient.id, period)
    if not plan:
        return f"<p>{period}: {tr.t('no_plans_year')}</p>"
    result = result_for(db, recipient.id, period, plan.plan_name)
    detail = {d["kpi"]: d for d in (json.loads(result.detail_json) if result else [])}
    rows = ""
    for kpi in plan.kpis:
        d = detail.get(kpi.kpi_name)
        if d and d.get("actual") is not None:
            actual, attain, rate = f"{d['actual']:,.2f}", f"{d['attainment_pct']:.1f}%", f"{d['rate_pct']:.1f}%"
        else:
            actual, attain, rate = "-", "-", "-"
        rows += (f"<tr><td>{tr.tl(kpi.kpi_name)}</td><td>{kpi.quota:,.2f}</td><td>{actual}</td>"
                 f"<td>{attain}</td><td>{tr.tl(kpi.curve.name)}</td><td>{kpi.weight_pct:g}%</td>"
                 f"<td>{rate}</td></tr>")
    summary = ""
    if result:
        adj = (f"　{tr.t('special_adjust')}：{result.adjustment_pct:+.2f} pp" if result.adjusted else "")
        summary = (f"<p><strong>{tr.t('unweighted_rate')}：{result.unweighted_rate_pct:.2f}%　"
                   f"{tr.t('weighted_rate')}：{result.weighted_rate_pct:.2f}%{adj}　"
                   f"{tr.t('quarter_total_rate')}：{result.final_rate_pct:.2f}%</strong></p>")
    return (f"<table {TABLE_STYLE}>"
            f"<tr><th>KPI</th><th>{tr.t('target')}</th><th>{tr.t('actual_col')}</th>"
            f"<th>{tr.t('attainment')}</th><th>Curve</th><th>{tr.t('weight_col')}</th>"
            f"<th>{tr.t('payout_rate')}</th></tr>"
            f"{rows}</table>{summary}")


def build_curve_summary(db, recipient: User, period: str, tr: Translator) -> str:
    """One table per curve: attainment interval → payout, with interval slope."""
    plan = plan_for(db, recipient.id, period)
    if not plan:
        return ""
    seen, parts = set(), []
    for kpi in plan.kpis:
        curve = kpi.curve
        if curve.id in seen:
            continue
        seen.add(curve.id)
        rows = ""
        for seg in curve.segments:
            rows += (f"<tr><td>{seg['x1']:g}% → {seg['x2']:g}%</td>"
                     f"<td>{seg['y1']:g}% → {seg['y2']:g}%</td>"
                     f"<td>{seg['slope']:.2f}</td></tr>")
        cap = (f"<p>{tr.t('cap')}：{curve.cap_pct:g}%</p>"
               if curve.cap_pct else f"<p>{tr.t('no_cap')}</p>")
        desc = f"<p>{tr.tl(curve.description)}</p>" if curve.description else ""
        parts.append(
            f"<p><strong>{tr.tl(curve.name)}</strong></p>"
            f"<table {TABLE_STYLE}>"
            f"<tr><th>{tr.t('attainment_range')}</th><th>{tr.t('payout_range')}</th>"
            f"<th>{tr.t('interval_slope')}</th></tr>"
            f"{rows}</table>{cap}{desc}"
        )
    return "".join(parts)


def render_letter_body(db, template: LetterTemplate, recipient: User, period: str,
                       message: str, token: str, tr: Translator) -> str:
    body = template.body_html
    for key, value in {
        "{{NAME}}": recipient.name,
        "{{PERIOD}}": period,
        "{{PLAN_TABLE}}": build_plan_table(db, recipient, period, tr),
        "{{CURVE_SUMMARY}}": build_curve_summary(db, recipient, period, tr),
        "{{MESSAGE}}": message or "",
    }.items():
        body = body.replace(key, value)
    ack_url = f"{BASE_URL}/letter/{token}"
    body += (f'<hr><p style="color:#888;font-size:12px">{tr.t("letter_ack_line")}'
             f'<a href="{ack_url}">{ack_url}</a></p>')
    return body


# ---------- letter log ----------

@router.get("/letters")
def letters_log(request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    if not _allowed(user):
        return flash("/", Translator(get_lang(request)).t("no_permission"))
    stmt = select(Letter).order_by(Letter.sent_at.desc(), Letter.id.desc())
    if _scope_bg(user):
        bg = _scope_bg(user)
        letters = [l for l in db.scalars(stmt).all() if l.recipient.bg == bg]
    else:
        letters = db.scalars(stmt).all()
    return render(request, "letters/log.html", user=user, letters=letters)


# ---------- templates ----------

@router.get("/letters/templates")
def templates_list(request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    if not _allowed(user):
        return flash("/", Translator(get_lang(request)).t("no_permission"))
    stmt = select(LetterTemplate).order_by(LetterTemplate.updated_at.desc())
    if _scope_bg(user):
        stmt = stmt.where(LetterTemplate.bg == user.bg)
    return render(request, "letters/templates.html", user=user, templates=db.scalars(stmt).all())


@router.get("/letters/templates/new")
def template_new(request: Request, user: User = Depends(require_user)):
    if not _allowed(user):
        return flash("/", Translator(get_lang(request)).t("no_permission"))
    return render(request, "letters/template_edit.html", user=user, template=None)


@router.get("/letters/templates/{tid}/edit")
def template_edit(tid: int, request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    template = db.get(LetterTemplate, tid)
    if not _allowed(user) or not template or (_scope_bg(user) and template.bg != user.bg):
        return flash("/letters/templates", Translator(get_lang(request)).t("no_permission"))
    return render(request, "letters/template_edit.html", user=user, template=template)


@router.post("/letters/templates/save")
def template_save(request: Request, tid: int = Form(0), name: str = Form(...), subject: str = Form(...),
                  body_html: str = Form(...), save_as_new: str = Form(""),
                  user: User = Depends(require_user), db=Depends(get_db)):
    t = Translator(get_lang(request))
    if not _allowed(user):
        return flash("/", t.t("no_permission"))
    template = db.get(LetterTemplate, tid) if tid else None
    if template and _scope_bg(user) and template.bg != user.bg:
        return flash("/letters/templates", t.t("no_permission"))
    if save_as_new == "true" or not template:
        template = LetterTemplate(bg=user.bg or "Global", created_by=user.id)
        db.add(template)
    template.name, template.subject, template.body_html = name, subject, body_html
    db.commit()
    return flash("/letters/templates", t.t("msg_template_saved", name=name))


# ---------- compose & send ----------

@router.get("/letters/compose")
def compose(request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    if not _allowed(user):
        return flash("/", Translator(get_lang(request)).t("no_permission"))
    stmt = select(LetterTemplate).order_by(LetterTemplate.name)
    if _scope_bg(user):
        stmt = stmt.where(LetterTemplate.bg == user.bg)
    templates = db.scalars(stmt).all()
    members_stmt = select(User).where(User.bg == user.bg, User.role != "ADMIN").order_by(User.employee_id) \
        if _scope_bg(user) else select(User).where(User.role != "ADMIN").order_by(User.employee_id)
    members = db.scalars(members_stmt).all()
    return render(request, "letters/compose.html", user=user, templates=templates,
                  members=members, periods=all_periods(db))


@router.post("/letters/send")
def send(request: Request, template_id: int = Form(...), period: str = Form(...), message: str = Form(""),
         recipients: list[int] = Form([]), user: User = Depends(require_user), db=Depends(get_db)):
    t = Translator(get_lang(request))
    if not _allowed(user):
        return flash("/", t.t("no_permission"))
    template = db.get(LetterTemplate, template_id)
    if not template:
        return flash("/letters/compose", t.t("msg_template_missing"))
    if not recipients:
        return flash("/letters/compose", t.t("msg_need_recipient"))
    sent = 0
    for uid in recipients:
        recipient = db.get(User, uid)
        if not recipient or (_scope_bg(user) and recipient.bg != user.bg):
            continue
        token = secrets.token_urlsafe(16)
        body = render_letter_body(db, template, recipient, period, message, token, t)
        mode = send_mail(recipient.email, template.subject, body)
        db.add(Letter(token=token, template_id=template.id, template_name=template.name,
                      recipient_id=recipient.id, period=period, subject=template.subject,
                      body_html=body, sent_by=user.id, send_mode=mode))
        sent += 1
    db.commit()
    mode_note = t.t("msg_smtp_on") if os.environ.get("SMTP_HOST") else t.t("msg_smtp_off")
    return flash("/letters", t.t("msg_sent", n=sent, mode=mode_note))


# ---------- public letter view & acknowledgement ----------

@router.get("/letter/{token}")
def letter_view(token: str, request: Request, user: User | None = Depends(current_user), db=Depends(get_db)):
    letter = db.scalars(select(Letter).where(Letter.token == token)).first()
    if not letter:
        return render(request, "letters/not_found.html", user=None)
    # Only the recipient (or an anonymous visitor from the email link) may acknowledge.
    can_ack = user is None or user.id == letter.recipient_id
    return render(request, "letters/view.html", user=user, letter=letter, can_ack=can_ack)


@router.post("/letter/{token}/read")
def letter_read(request: Request, token: str, user: User | None = Depends(current_user), db=Depends(get_db)):
    from datetime import datetime, timezone

    t = Translator(get_lang(request))
    letter = db.scalars(select(Letter).where(Letter.token == token)).first()
    if letter and not letter.read_at:
        can_ack = user is None or user.id == letter.recipient_id
        if can_ack:
            letter.read_at = datetime.now(timezone.utc)
            db.commit()
        else:
            return flash(f"/letter/{token}", t.t("msg_ack_denied"))
    return flash(f"/letter/{token}", t.t("msg_ack_done"))
