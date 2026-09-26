"""Notification letters: templates, compose & send, public read-acknowledgement.

v5.0: letters NO LONGER import their own data. A letter simply renders whatever is
already in the library for that (recipient, period). Where a quarter has no actuals
yet (start-of-year before performance lands), the performance-related cells stay blank.

Letter bodies embed per-KPI tables and a Curve table that shows, per interval,
how much attainment maps to how much payout plus the interval slope.
"""

import json
import os
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy import select

from ..csvio import to_csv
from ..deps import bg_filter, current_user, get_db, require_user
from ..i18n import Translator, get_lang, translate_headers
from ..mailer import send_mail, smtp_enabled
from ..models import Letter, LetterTemplate, User
from ..ui import render
from .auth import flash
from .views import all_periods, plan_for, result_for

router = APIRouter()

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")

TABLE_STYLE = "border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse'"


def _allowed(user: User) -> bool:
    return user.role in ("BG_ADMIN", "ADMIN")


def _scope_bg(user: User) -> set[str] | None:
    """None means global (ADMIN); otherwise the set of BGs this actor manages."""
    return bg_filter(user)


GLOBAL_BG = "Global"


def _template_scope_clause(user: User):
    """F4: letter templates are shared across ALL admins (platform ADMIN and every
    BG_ADMIN), so the list/compose scope is unfiltered. ``None`` means no WHERE clause."""
    return None


def _can_view_template(user: User, template: LetterTemplate) -> bool:
    """Every allowed admin may open (view) any template — sharing is the whole point of F4."""
    return True


def _can_edit_template(user: User, template: LetterTemplate) -> bool:
    """F4: only the creator may edit a template in place. Anyone else sees it read-only
    and must copy it first (which makes them the new creator)."""
    return template.created_by == user.id


def _can_delete_template(user: User, template: LetterTemplate) -> bool:
    """F4: a creator may delete their own template; a platform ADMIN may delete any."""
    return user.role == "ADMIN" or template.created_by == user.id


# ---------- placeholders rendering ----------

def build_plan_table(db, recipient: User, period: str, tr: Translator) -> str:
    """Plan structure only (feature #10): no actuals, no rates — the letter's
    'your plan for this quarter' block. Performance numbers live in
    build_performance_table()."""
    plan = plan_for(db, recipient.id, period)
    if not plan:
        return f"<p>{period}: {tr.t('no_plans_year')}</p>"
    rows = ""
    for kpi in plan.kpis:
        rows += (f"<tr><td>{tr.tl(kpi.kpi_name)}</td><td>{kpi.weight_pct:g}%</td>"
                 f"<td>{kpi.quota:,.2f}</td><td>{tr.tl(kpi.curve.name)}</td></tr>")
    return (f"<table {TABLE_STYLE}>"
            f"<tr><th>KPI</th><th>{tr.t('weight_col')}</th><th>{tr.t('target')}</th>"
            f"<th>{tr.t('curve_col')}</th></tr>{rows}</table>")


def build_performance_table(db, recipient: User, period: str, tr: Translator) -> str:
    """Per-KPI performance breakdown (feature #10): weight / target / actual /
    attainment / curve / raw payout rate / weighted contribution. Weighted
    contribution = weight% / 100 * raw rate, matching the platform's locked
    weighted-rate convention (Σ contribution, no renormalisation).

    v5.0: a KPI with no actual yet (a fresh quarter before performance data lands)
    leaves its actual / attainment / rate / contribution cells BLANK — not "-" and
    not 0 — so nothing implies the person was measured."""
    plan = plan_for(db, recipient.id, period)
    if not plan:
        return ""
    result = result_for(db, recipient.id, period, plan.plan_name)
    detail = {d["kpi"]: d for d in (json.loads(result.detail_json) if result else [])}
    rows = ""
    total_contrib = 0.0
    has_any_actual = False
    for kpi in plan.kpis:
        d = detail.get(kpi.kpi_name)
        if d and d.get("actual") is not None:
            has_any_actual = True
            actual = f"{d['actual']:,.2f}"
            attain = f"{d['attainment_pct']:.1f}%"
            raw = d["rate_pct"]
            contrib = kpi.weight_pct / 100.0 * raw
            total_contrib += contrib
            raw_s, contrib_s = f"{raw:.1f}%", f"{contrib:.2f}%"
        else:
            actual = attain = raw_s = contrib_s = ""   # v5.0 blank — no performance data
        rows += (f"<tr><td>{tr.tl(kpi.kpi_name)}</td><td>{kpi.weight_pct:g}%</td>"
                 f"<td>{kpi.quota:,.2f}</td><td>{actual}</td><td>{attain}</td>"
                 f"<td>{tr.tl(kpi.curve.name)}</td><td>{raw_s}</td><td>{contrib_s}</td></tr>")
    summary = ""
    if result and has_any_actual:
        adj = (f"　{tr.t('special_adjust')}：{result.adjustment_pct:+.2f} pp" if result.adjusted else "")
        final_part = (f"　{tr.t('quarter_total_rate')}：{result.final_rate_pct:.2f}%" if result.adjusted else "")
        summary = (f"<p><strong>{tr.t('weighted_rate')}：{result.weighted_rate_pct:.2f}%{adj}"
                   f"{final_part}</strong></p>")
    return (f"<table {TABLE_STYLE}>"
            f"<tr><th>KPI</th><th>{tr.t('weight_col')}</th><th>{tr.t('target')}</th>"
            f"<th>{tr.t('actual_col')}</th><th>{tr.t('attainment')}</th>"
            f"<th>{tr.t('curve_col')}</th><th>{tr.t('raw_rate')}</th>"
            f"<th>{tr.t('weighted_contribution')}</th></tr>{rows}</table>{summary}")


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


def letter_substitutions(db, recipient: User, period: str, message: str,
                         tr: Translator) -> dict:
    """Scalar (non-table) placeholders, shared by BOTH subject and body so the subject
    line can use {{PERIOD}} / {{NAME}} etc. (v5.0 #15 — the reported subject bug)."""
    plan = plan_for(db, recipient.id, period)
    return {
        "{{NAME}}": recipient.name,
        "{{EMPLOYEE_ID}}": recipient.employee_id,
        "{{EMAIL}}": recipient.email or "",
        "{{BG}}": tr.tl(recipient.bg) if recipient.bg else "",
        "{{DEPARTMENT}}": tr.tl(recipient.department) if recipient.department else "",
        "{{JOB_TITLE}}": tr.tl(recipient.job_title) if recipient.job_title else "",
        "{{MANAGER}}": recipient.manager.name if recipient.manager else "",
        "{{PERIOD}}": period,
        "{{PLAN_NAME}}": (tr.tl(plan.plan_name) if plan else ""),
        "{{MESSAGE}}": message or "",
    }


def render_letter_subject(db, template: LetterTemplate, recipient: User, period: str,
                          message: str, tr: Translator) -> str:
    """v5.0 #15: expand placeholders in the SUBJECT line (previously stored raw, which is
    why '{{PERIOD}} 奖金通知' showed literally)."""
    subject = template.subject
    for key, value in letter_substitutions(db, recipient, period, message, tr).items():
        subject = subject.replace(key, value)
    return subject


def render_letter_body(db, template: LetterTemplate, recipient: User, period: str,
                       message: str, token: str, tr: Translator) -> str:
    body = template.body_html
    substitutions = letter_substitutions(db, recipient, period, message, tr)
    substitutions.update({
        "{{PLAN_TABLE}}": build_plan_table(db, recipient, period, tr),
        "{{PERFORMANCE_TABLE}}": build_performance_table(db, recipient, period, tr),
        "{{CURVE_SUMMARY}}": build_curve_summary(db, recipient, period, tr),
    })
    for key, value in substitutions.items():
        body = body.replace(key, value)
    ack_url = f"{BASE_URL}/letter/{token}"
    body += (f'<hr><p style="color:#888;font-size:12px">{tr.t("letter_ack_line")}'
             f'<a href="{ack_url}">{ack_url}</a></p>')
    return body


# ---------- letter log ----------

@router.get("/letters")
def letters_log(request: Request, period: str = "", user: User = Depends(require_user), db=Depends(get_db)):
    if not _allowed(user):
        return flash("/", Translator(get_lang(request)).t("no_permission"))
    stmt = select(Letter).order_by(Letter.sent_at.desc(), Letter.id.desc())
    if period.strip():
        stmt = stmt.where(Letter.period == period.strip())
    scope = _scope_bg(user)
    if scope is not None:
        letters = [l for l in db.scalars(stmt).all() if l.recipient and l.recipient.bg in scope]
    else:
        letters = db.scalars(stmt).all()
    return render(request, "letters/log.html", user=user, letters=letters,
                  periods=all_periods(db), period=period.strip(), scope=scope)


@router.get("/letters/export.csv")
def letters_export(request: Request, period: str = "", user: User = Depends(require_user), db=Depends(get_db)):
    """v5.0 #16: export the (scoped) letter log — all periods or one chosen quarter."""
    t = Translator(get_lang(request))
    if not _allowed(user):
        return flash("/", t.t("no_permission"))
    stmt = select(Letter).order_by(Letter.sent_at.desc(), Letter.id.desc())
    p = period.strip()
    if p:
        stmt = stmt.where(Letter.period == p)
    scope = _scope_bg(user)
    header = translate_headers(
        ["token", "recipient_employee_id", "recipient_name", "bg", "period",
         "template_name", "subject", "send_mode", "sent_at", "read_at"], get_lang(request))
    rows = [header]
    for l in db.scalars(stmt).all():
        if scope is not None and (not l.recipient or l.recipient.bg not in scope):
            continue
        rows.append([
            l.token,
            l.recipient.employee_id if l.recipient else "",
            l.recipient.name if l.recipient else "",
            l.recipient.bg if l.recipient else "",
            l.period, l.template_name, l.subject, l.send_mode,
            l.sent_at.strftime("%Y-%m-%d %H:%M") if l.sent_at else "",
            l.read_at.strftime("%Y-%m-%d %H:%M") if l.read_at else "",
        ])
    name = "letters" + (f"_{p}" if p else "_all") + ".csv"
    return Response(
        "\ufeff" + to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------- templates ----------

@router.get("/letters/templates")
def templates_list(request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    if not _allowed(user):
        return flash("/", Translator(get_lang(request)).t("no_permission"))
    stmt = select(LetterTemplate).order_by(LetterTemplate.updated_at.desc())
    clause = _template_scope_clause(user)
    if clause is not None:
        stmt = stmt.where(clause)
    rows = [{"tpl": tpl,
             "editable": _can_edit_template(user, tpl),
             "deletable": _can_delete_template(user, tpl)}
            for tpl in db.scalars(stmt).all()]
    return render(request, "letters/templates.html", user=user, rows=rows)


@router.get("/letters/templates/new")
def template_new(request: Request, user: User = Depends(require_user)):
    if not _allowed(user):
        return flash("/", Translator(get_lang(request)).t("no_permission"))
    return render(request, "letters/template_edit.html", user=user, template=None)


@router.get("/letters/templates/{tid}/edit")
def template_edit(tid: int, request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    template = db.get(LetterTemplate, tid)
    if not _allowed(user) or not template or not _can_view_template(user, template):
        return flash("/letters/templates", Translator(get_lang(request)).t("no_permission"))
    return render(request, "letters/template_edit.html", user=user, template=template,
                  can_edit=_can_edit_template(user, template))


@router.post("/letters/templates/save")
def template_save(request: Request, tid: int = Form(0), name: str = Form(...), subject: str = Form(...),
                  body_html: str = Form(...), save_as_new: str = Form(""),
                  user: User = Depends(require_user), db=Depends(get_db)):
    t = Translator(get_lang(request))
    if not _allowed(user):
        return flash("/", t.t("no_permission"))
    template = db.get(LetterTemplate, tid) if tid else None
    if template and save_as_new != "true" and not _can_edit_template(user, template):
        return flash("/letters/templates", t.t("no_permission"))
    if save_as_new == "true" or not template:
        template = LetterTemplate(bg=user.bg or "Global", created_by=user.id)
        db.add(template)
    template.name, template.subject, template.body_html = name, subject, body_html
    db.commit()
    return flash("/letters/templates", t.t("msg_template_saved", name=name))


@router.post("/letters/templates/{tid}/copy")
def template_copy(tid: int, request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    """F4: anyone may copy a shared template into one they own, then edit that copy."""
    t = Translator(get_lang(request))
    if not _allowed(user):
        return flash("/", t.t("no_permission"))
    src = db.get(LetterTemplate, tid)
    if not src:
        return flash("/letters/templates", t.t("msg_template_missing"))
    copy = LetterTemplate(name=f"{src.name}{t.t('template_copy_suffix')}",
                          bg=user.bg or GLOBAL_BG, subject=src.subject,
                          body_html=src.body_html, created_by=user.id)
    db.add(copy)
    db.commit()
    return flash(f"/letters/templates/{copy.id}/edit", t.t("msg_template_copied", name=copy.name))


@router.post("/letters/templates/{tid}/delete")
def template_delete(tid: int, request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    """F4: the creator may delete their own template; a platform ADMIN may delete any."""
    t = Translator(get_lang(request))
    if not _allowed(user):
        return flash("/", t.t("no_permission"))
    template = db.get(LetterTemplate, tid)
    if not template:
        return flash("/letters/templates", t.t("msg_template_missing"))
    if not _can_delete_template(user, template):
        return flash("/letters/templates", t.t("no_permission"))
    name = template.name
    db.delete(template)
    db.commit()
    return flash("/letters/templates", t.t("msg_template_deleted", name=name))


# ---------- compose & send ----------

@router.get("/letters/compose")
def compose(request: Request, user: User = Depends(require_user), db=Depends(get_db)):
    if not _allowed(user):
        return flash("/", Translator(get_lang(request)).t("no_permission"))
    scope = _scope_bg(user)
    tmpl_stmt = select(LetterTemplate).order_by(LetterTemplate.name)
    clause = _template_scope_clause(user)
    if clause is not None:
        tmpl_stmt = tmpl_stmt.where(clause)
    templates = db.scalars(tmpl_stmt).all()
    members_stmt = select(User).where(User.role != "ADMIN")
    if scope is not None:
        members_stmt = members_stmt.where(User.bg.in_(scope if scope else ["__none__"]))
    members = db.scalars(members_stmt.order_by(User.employee_id)).all()
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
    scope = _scope_bg(user)
    sent = 0
    any_smtp = False
    for uid in recipients:
        recipient = db.get(User, uid)
        if not recipient or (scope is not None and recipient.bg not in scope):
            continue
        token = secrets.token_urlsafe(16)
        subject = render_letter_subject(db, template, recipient, period, message, t)
        body = render_letter_body(db, template, recipient, period, message, token, t)
        mode = send_mail(recipient.email, subject, body)
        any_smtp = any_smtp or mode == "smtp"
        db.add(Letter(token=token, template_id=template.id, template_name=template.name,
                      recipient_id=recipient.id, period=period, subject=subject,
                      body_html=body, sent_by=user.id, send_mode=mode))
        sent += 1
    db.commit()
    mode_note = t.t("msg_smtp_on") if any_smtp or smtp_enabled() else t.t("msg_smtp_off")
    return flash("/letters", t.t("msg_sent", n=sent, mode=mode_note))


@router.post("/letters/mailtest")
def mailtest(request: Request, user=Depends(require_user), db=Depends(get_db)):
    """Ping the configured mail transports (no message sent) and report back."""
    t = Translator(get_lang(request))
    if not _allowed(user):
        return flash("/", t.t("no_permission"))
    from ..mailer import test_connection

    results = test_connection()
    lines = [f"{'✅' if r['ok'] else '❌'} {r['transport'].upper()}：{r['detail']}" for r in results]
    return flash("/letters/compose", "\n".join(lines))


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
