"""Admin console: users (+ proxy BG admin), curves, unified quarterly big-table import
(versioned, two-pass, shared with BG admins), data deletion (CSV + audit), two-pass
calculation, adjustments (single + batch CSV), seals, export (year + BG),
language/translation management."""

import json

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from ..calc import apply_adjustment, is_locked, run_calculation
from ..csvio import (_csv_rows_for_calc_template, actual_delete_template_rows, adjustment_template_rows,
                     apply_deletions, big_error_rows, big_summary, big_template_rows, collect_originals,
                     decode_csv, deletion_logs, execute_big_import, execute_user_import, export_results_rows,
                     import_labels, label_rows, parse_adjustment_rows, parse_big_rows, parse_user_rows,
                     plan_delete_template_rows, recent_periods, resolve_employee, to_csv, user_error_rows,
                     user_summary, user_template_rows)
from ..curves import parse_points
from ..deps import SESSION_COOKIE, SESSION_MAX_AGE, get_db, home_for, make_session, require_roles
from ..i18n import Translator, get_lang, invalidate_label_cache
from ..models import Adjustment, BonusPlan, BonusResult, CalcRun, Curve, DataOpLog, Label, Lock, User
from ..security import hash_password
from ..ui import render
from .auth import flash

router = APIRouter(prefix="/admin")  # per-route role dependencies (import pages also allow BG_ADMIN)


def _csv_response(rows: list[list], filename: str) -> Response:
    return Response(
        "\ufeff" + to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _t(request: Request) -> Translator:
    return Translator(get_lang(request))


@router.get("")
def dashboard(request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    runs = db.scalars(select(CalcRun).order_by(CalcRun.created_at.desc(), CalcRun.id.desc())).all()
    locks = db.scalars(select(Lock).order_by(Lock.locked_at.desc())).all()
    bgs = sorted({u.bg for u in db.scalars(select(User)).all() if u.bg})
    periods = sorted(db.scalars(select(BonusPlan.period).distinct()).all(), reverse=True)
    return render(request, "admin/dashboard.html", user=user, runs=runs, locks=locks, bgs=bgs, periods=periods)


# ---------- users ----------

@router.get("/users")
def users_page(request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    users = db.scalars(select(User).order_by(User.employee_id)).all()
    return render(request, "admin/users.html", user=user, users=users)


@router.post("/users")
def users_create(request: Request, name: str = Form(...), employee_id: str = Form(...),
                 email: str = Form(...), role: str = Form("EMPLOYEE"), bg: str = Form(""),
                 department: str = Form(""), job_title: str = Form(""), password: str = Form(""),
                 user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    exists = db.scalars(
        select(User).where((User.employee_id == employee_id) | (User.email == email))
    ).first()
    if exists:
        return flash("/admin/users", t.t("msg_user_exists", uid=employee_id))
    db.add(User(name=name, employee_id=employee_id, email=email, role=role.upper(), bg=bg or None,
                department=department or None, job_title=job_title or None,
                password_hash=hash_password(password or employee_id)))
    db.commit()
    return flash("/admin/users", t.t("msg_user_created", uid=employee_id,
                                     pw=t.t("msg_pw_custom" if password else "msg_pw_default")))


# ---------- batch user import (ADMIN only, two-pass: create / update / ignore identical) ----------

@router.get("/users/import/template.csv")
def users_import_template(user=Depends(require_roles("ADMIN"))):
    return _csv_response(user_template_rows(), "users_import_template.csv")


@router.post("/users/import/preview")
async def users_import_preview(request: Request, file: UploadFile | None = None,
                               user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    if file is None or not file.filename:
        return flash("/admin/users", t.t("msg_no_file"))
    text = decode_csv(await file.read())
    entries = parse_user_rows(db, text, get_lang(request))
    if not entries:
        return flash("/admin/users", t.t("msg_no_rows"))
    return render(request, "admin/user_import_preview.html", user=user, rows=entries,
                  csv_text=text, summary=user_summary(entries))


@router.post("/users/import/execute")
def users_import_execute(request: Request, csv_text: str = Form(...),
                         user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    msg = execute_user_import(db, csv_text, user, get_lang(request))
    return flash("/admin/users", msg)


@router.post("/users/import/errors.csv")
def users_import_errors(request: Request, csv_text: str = Form(...),
                        user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    rows = user_error_rows(db, csv_text, get_lang(request))
    return _csv_response(rows, "users_import_errors.csv")


@router.post("/users/{uid}/toggle")
def users_toggle(request: Request, uid: int, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    target = db.get(User, uid)
    if target and target.id != user.id:
        target.is_active = not target.is_active
        db.commit()
    return flash("/admin/users", _t(request).t("msg_user_toggled"))


# ---------- curves ----------

@router.get("/curves")
def curves_page(request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    curves = db.scalars(select(Curve).order_by(Curve.name)).all()
    return render(request, "admin/curves.html", user=user, curves=curves, editing=None)


@router.get("/curves/{cid}")
def curve_edit(cid: int, request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    curves = db.scalars(select(Curve).order_by(Curve.name)).all()
    return render(request, "admin/curves.html", user=user, curves=curves, editing=db.get(Curve, cid))


@router.post("/curves")
def curves_save(request: Request, cid: int = Form(0), name: str = Form(...), points_text: str = Form(...),
                cap_pct: str = Form(""), description: str = Form(""),
                user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    try:
        points = parse_points(points_text)
    except ValueError as e:
        return flash("/admin/curves", str(e))
    cap = float(cap_pct) if cap_pct.strip() else None
    curve = db.get(Curve, cid) if cid else Curve(created_by=user.id)
    name_query = select(Curve).where(Curve.name == name)
    if cid:
        name_query = name_query.where(Curve.id != cid)
    if db.scalars(name_query).first():
        return flash("/admin/curves", t.t("msg_curve_exists", name=name))
    curve.name, curve.points_json, curve.cap_pct, curve.description = name, json.dumps(points), cap, description
    db.add(curve)
    db.commit()
    return flash("/admin/curves", t.t("msg_curve_saved", name=name))


# ---------- unified quarterly big-table import (ADMIN + BG_ADMIN, two-pass) ----------

def _import_bg_scope(user: User) -> str | None:
    """BG admins only see/modify their own BG; platform admins see everything."""
    return user.bg if user.role == "BG_ADMIN" else None


@router.get("/import")
def import_page(request: Request, user=Depends(require_roles("ADMIN", "BG_ADMIN")), db=Depends(get_db)):
    return render(request, "admin/import.html", user=user, periods=recent_periods(db))


@router.get("/import/template.csv")
def import_template(request: Request, period: str = "",
                    user=Depends(require_roles("ADMIN", "BG_ADMIN")), db=Depends(get_db)):
    """Blank template, or prefilled from one of the recent quarters (permission-scoped)."""
    rows = big_template_rows(db, period=period.strip() or None, bg=_import_bg_scope(user),
                             with_actual=True)
    name = f"quarter_import_template{'_' + period.strip() if period.strip() else ''}.csv"
    return _csv_response(rows, name)


@router.post("/import/preview")
async def import_preview(request: Request, file: UploadFile | None = None,
                         user=Depends(require_roles("ADMIN", "BG_ADMIN")), db=Depends(get_db)):
    t = _t(request)
    if file is None or not file.filename:
        return flash("/admin/import", t.t("msg_no_file"))
    text = decode_csv(await file.read())
    entries = parse_big_rows(db, text, user, get_lang(request), with_actual=True)
    if not entries:
        return flash("/admin/import", t.t("msg_no_rows"))
    return render(request, "import_preview.html", user=user, rows=entries, csv_text=text,
                  summary=big_summary(entries), with_actual=True,
                  execute_url="/admin/import/execute", errors_url="/admin/import/errors.csv",
                  back_url="/admin/import")


@router.post("/import/execute")
def import_execute(request: Request, csv_text: str = Form(...),
                   user=Depends(require_roles("ADMIN", "BG_ADMIN")), db=Depends(get_db)):
    from ..deps import session_payload

    payload = session_payload(request) or {}
    proxy_note = ""
    if payload.get("p"):
        original = db.get(User, payload["p"])
        if original:
            proxy_note = f"proxy by {original.employee_id}"
    msg = execute_big_import(db, csv_text, user, get_lang(request), with_actual=True,
                             proxy_note=proxy_note)
    return flash("/admin/import", msg)


@router.post("/import/errors.csv")
def import_errors(request: Request, csv_text: str = Form(...),
                  user=Depends(require_roles("ADMIN", "BG_ADMIN")), db=Depends(get_db)):
    rows = big_error_rows(db, csv_text, user, get_lang(request), with_actual=True)
    return _csv_response(rows, "import_errors.csv")


# ---------- proxy: platform admin acts as a BG admin ----------

@router.post("/proxy/{uid}")
def proxy_start(request: Request, uid: int, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    target = db.get(User, uid)
    if not target or target.role != "BG_ADMIN" or not target.is_active:
        return flash("/admin/users", t.t("msg_proxy_bad_target"))
    db.add(DataOpLog(op_type="PROXY", entity="session",
                     entity_ref=f"{user.employee_id} → {target.employee_id}",
                     reason="start proxy", created_by=user.id))
    db.commit()
    from urllib.parse import quote

    dest = f"{home_for(target)}?msg={quote(t.t('msg_proxy_started', name=target.name))}"
    response = RedirectResponse(dest, status_code=303)
    response.set_cookie(SESSION_COOKIE, make_session(target.id, proxy_of=user.id),
                        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")
    return response


# ---------- data deletion via CSV (with audit log) ----------

@router.get("/data")
def data_page(request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    logs = deletion_logs(db)
    return render(request, "admin/data.html", user=user, logs=logs,
                  template_periods=recent_periods(db))


@router.get("/data/delete-template.csv")
def delete_template(request: Request, entity: str = "actual", period: str = "",
                    user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    p = period.strip() or None
    if entity == "plan":
        return _csv_response(plan_delete_template_rows(db, period=p), "delete_plans_template.csv")
    return _csv_response(actual_delete_template_rows(db, period=p), "delete_actuals_template.csv")


@router.post("/data/delete")
async def data_delete(request: Request, entity: str = Form("actual"), file: UploadFile | None = None,
                      user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    if file is None or not file.filename:
        return flash("/admin/data", t.t("msg_no_file"))
    try:
        text = decode_csv(await file.read())
        msg = apply_deletions(db, text, entity, user, get_lang(request))
    except Exception as e:  # noqa: BLE001
        return flash("/admin/data", f"{t.t('delete')}: {e}")
    return flash("/admin/data", f"{t.t('actual' if entity == 'actual' else 'plan')}：{msg}")


# ---------- two-pass calculation via CSV ----------

@router.get("/calc")
def calc_page(request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    periods = sorted(db.scalars(select(BonusPlan.period).distinct()).all(), reverse=True)
    return render(request, "admin/calc.html", user=user, periods=periods,
                  template_periods=recent_periods(db))


@router.get("/calc/template.csv")
def calc_template(request: Request, period: str = "",
                  user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    """One row per current plan (period, employee); admin appends action=计算."""
    return _csv_response(_csv_rows_for_calc_template(db, period=period.strip() or None),
                         "calc_template.csv")


def _parse_calc_rows(db, text: str, t: Translator) -> list[dict]:
    """Pass-1 read: validate each row. Returns rows with status."""
    out = []
    from ..csvio import _rows
    for row in _rows(text):
        action = row.get("action", "").strip()
        if not action:
            continue
        period = row.get("period")
        employee = resolve_employee(db, row.get("employee_id"), row.get("name"))
        entry = {"period": period, "emp_ext": row.get("employee_id") or row.get("name"),
                 "employee": employee, "status": t.t("row_ok"), "note": "", "ok": True}
        if not period:
            entry.update(status=t.t("row_no_period"), note="period", ok=False)
        elif employee is None:
            entry.update(status=t.t("row_no_employee"), note="", ok=False)
        else:
            plan = db.scalars(
                select(BonusPlan).where(
                    BonusPlan.period == period, BonusPlan.employee_id == employee.id,
                    BonusPlan.is_current == True, BonusPlan.is_deleted == False,  # noqa: E712
                )).first()
            if plan is None:
                entry.update(status=t.t("row_no_plan"), note="", ok=False)
            elif is_locked(db, period, employee.bg):
                entry.update(status=t.t("row_sealed"), note=f"{period}/{employee.bg}", ok=False)
            else:
                entry["note"] = f"{employee.name} · {plan.plan_name}"
        out.append(entry)
    return out


@router.post("/calc/preview")
async def calc_preview(request: Request, file: UploadFile | None = None,
                       user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    if file is None or not file.filename:
        return flash("/admin/calc", t.t("msg_no_file"))
    text = decode_csv(await file.read())
    rows = _parse_calc_rows(db, text, t)
    if not rows:
        return flash("/admin/calc", t.t("no_action_rows"))
    return render(request, "admin/calc_preview.html", user=user, rows=rows, csv_text=text)


@router.post("/calc/execute")
def calc_execute(request: Request, csv_text: str = Form(...), note: str = Form(""),
                 user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    rows = _parse_calc_rows(db, csv_text, t)
    targets: dict[str, list[int]] = {}
    for entry in rows:
        if not entry["ok"]:
            continue
        targets.setdefault(entry["period"], []).append(entry["employee"].id)
    if not targets:
        return flash("/admin/calc", t.t("no_action_rows"))
    run_ids, computed, skipped = [], 0, 0
    try:
        for period, emp_ids in targets.items():
            run, stats = run_calculation(db, period, user, note, emp_ids, get_lang(request))
            run_ids.append(run.id)
            computed += stats["computed"]
            skipped += len(stats["skipped"])
    except ValueError as e:
        return flash("/admin/calc", str(e))
    msg = t.t("msg_calc_done", n=computed) + (t.t("msg_calc_skipped", n=skipped) if skipped else "")
    dest = f"/admin/runs/{run_ids[0]}" if len(run_ids) == 1 else "/admin"
    return flash(dest, msg)


# ---------- calculation runs (quick trigger + detail) ----------

@router.post("/runs")
def trigger_run(request: Request, period: str = Form(...), note: str = Form(""),
                user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    try:
        run, stats = run_calculation(db, period.strip(), user, note, lang=get_lang(request))
    except ValueError as e:
        return flash("/admin", str(e))
    msg = t.t("msg_run_created", rid=run.id, period=period, n=stats["computed"])
    if stats["skipped"]:
        msg += t.t("msg_calc_skipped", n=len(stats["skipped"]))
    return flash(f"/admin/runs/{run.id}", msg)


@router.get("/runs/{rid}")
def run_detail(rid: int, request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    run = db.get(CalcRun, rid)
    if not run:
        return flash("/admin", "404")
    results = db.scalars(select(BonusResult).where(BonusResult.run_id == rid)).all()
    return render(request, "admin/run_detail.html", user=user, run=run, results=results, json=json)


# ---------- adjustments (single + batch CSV) ----------

@router.get("/adjust")
def adjust_page(request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    adjustments = db.scalars(select(Adjustment).order_by(Adjustment.created_at.desc(), Adjustment.id.desc())).all()
    employees = db.scalars(select(User).where(User.role != "ADMIN").order_by(User.employee_id)).all()
    periods = sorted(db.scalars(select(BonusPlan.period).distinct()).all(), reverse=True)
    return render(request, "admin/adjust.html", user=user, adjustments=adjustments,
                  employees=employees, periods=periods, template_periods=recent_periods(db))


@router.post("/adjust")
def adjust_save(request: Request, employee_id: int = Form(...), period: str = Form(...),
                adjustment_pct: float = Form(...), reason: str = Form(...),
                user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    if not reason.strip():
        return flash("/admin/adjust", t.t("msg_adjust_reason_required"))
    try:
        apply_adjustment(db, employee_id, period, adjustment_pct, reason.strip(), user, get_lang(request))
    except ValueError as e:
        return flash("/admin/adjust", str(e))
    return flash("/admin/adjust", t.t("msg_adjust_recorded", period=period, delta=f"{adjustment_pct:+g}"))


@router.get("/adjust/template.csv")
def adjust_template(request: Request, period: str = "",
                    user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    return _csv_response(adjustment_template_rows(db, period=period.strip() or None),
                         "adjustments_template.csv")


@router.post("/adjust/preview")
async def adjust_preview(request: Request, file: UploadFile | None = None,
                         user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    if file is None or not file.filename:
        return flash("/admin/adjust", t.t("msg_no_file"))
    text = decode_csv(await file.read())
    rows = parse_adjustment_rows(db, text, get_lang(request))
    if not rows:
        return flash("/admin/adjust", t.t("no_action_rows"))
    return render(request, "admin/adjust_preview.html", user=user, rows=rows, csv_text=text)


@router.post("/adjust/execute")
def adjust_execute(request: Request, csv_text: str = Form(...),
                   user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    rows = parse_adjustment_rows(db, csv_text, get_lang(request))
    ok = skip = 0
    for entry in rows:
        if not entry["ok"]:
            skip += 1
            continue
        try:
            apply_adjustment(db, entry["employee"].id, entry["period"], entry["delta"],
                             entry["reason"], user, get_lang(request))
            ok += 1
        except ValueError:
            skip += 1
    if ok == 0 and skip == 0:
        return flash("/admin/adjust", t.t("no_action_rows"))
    return flash("/admin/adjust", t.t("msg_adjust_batch", ok=ok, skip=skip))


# ---------- seals (locks) ----------

@router.post("/locks")
def add_lock(request: Request, period: str = Form(...), bg: str = Form(...),
             user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    exists = db.scalars(select(Lock).where(Lock.period == period, Lock.bg == bg)).first()
    if exists:
        return flash("/admin", t.t("msg_sealed_exists", period=period, bg=bg))
    db.add(Lock(period=period.strip(), bg=bg.strip(), locked_by=user.id))
    db.commit()
    return flash("/admin", t.t("msg_sealed_done", period=period, bg=bg))


# ---------- export (year + BG selectable) ----------

@router.get("/export")
def export_page(request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    years = sorted({p.split("-")[0] for p in db.scalars(select(CalcRun.period).distinct()).all()},
                   reverse=True)
    bgs = sorted({u.bg for u in db.scalars(select(User)).all() if u.bg})
    return render(request, "admin/export.html", user=user, years=years, bgs=bgs)


@router.get("/export.csv")
def export_csv(period: str | None = None, bg: str | None = None, year: str | None = None,
               user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    rows = export_results_rows(db, bg=bg or None, period=period or None, year=year or None)
    name = "bonus_results" + (f"_{year}" if year else "") + (f"_{bg}" if bg else "") \
           + (f"_{period}" if period else "") + ".csv"
    return _csv_response(rows, name)


# ---------- language management (translations of DB field values) ----------

@router.get("/labels")
def labels_page(request: Request, user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    labels = {l.original: l for l in db.scalars(select(Label)).all()}
    rows = []
    for original in collect_originals(db):
        rows.append(labels.get(original) or Label(original=original))
    for original, label in labels.items():  # labels whose source value is gone
        if original not in {r.original for r in rows}:
            rows.append(label)
    return render(request, "admin/labels.html", user=user, labels=rows)


@router.post("/labels")
def labels_save(request: Request, original: str = Form(...), zh: str = Form(""), en: str = Form(""),
                user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    original = original.strip()
    if not original:
        return flash("/admin/labels", t.t("msg_no_file"))
    label = db.scalars(select(Label).where(Label.original == original)).first()
    if label is None:
        label = Label(original=original)
        db.add(label)
    label.zh, label.en = zh.strip(), en.strip()
    db.add(DataOpLog(op_type="IMPORT", entity="label", entity_ref=original,
                     reason="single label edit", created_by=user.id))
    db.commit()
    invalidate_label_cache()
    return flash("/admin/labels", t.t("msg_labels_saved", n=1))


@router.post("/labels/import")
async def labels_import(request: Request, file: UploadFile | None = None,
                        user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    t = _t(request)
    if file is None or not file.filename:
        return flash("/admin/labels", t.t("msg_no_file"))
    text = decode_csv(await file.read())
    msg = import_labels(db, text, user, get_lang(request))
    return flash("/admin/labels", msg)


@router.get("/labels/export.csv")
def labels_export(user=Depends(require_roles("ADMIN")), db=Depends(get_db)):
    return _csv_response(label_rows(db), "labels_template.csv")
