"""CSV import/export, versioned imports, soft-delete with audit log, batch adjustments,
label (translation) upserts.

Conventions
-----------
* Every imported record carries an automatic ``imported_at`` timestamp and a ``version``.
* Records are matched by 工号(employee_id); when absent, matched by 姓名(name).
* Re-import creates a NEW version and deactivates the old one. Only the latest
  (``is_current``) non-deleted version is used; old versions are locked/immutable.
* Deletions are soft (is_deleted=True) and MUST leave a reason in DataOpLog.
* All rates are percentages; no bonus base/amount is stored.
"""

import csv
import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .calc import is_locked
from .i18n import DEFAULT_LANG, Translator, invalidate_label_cache
from .models import Actual, BonusPlan, Curve, DataOpLog, Label, PlanKpi, User
from .security import hash_password


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def decode_csv(raw: bytes) -> str:
    """Tolerant decode: UTF-8 (with BOM) first, then GBK (common Excel export)."""
    for enc in ("utf-8-sig", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _rows(text: str) -> list[dict]:
    text = text.lstrip("\ufeff")
    return [
        {k.strip(): (v or "").strip() for k, v in row.items() if k is not None}
        for row in csv.DictReader(io.StringIO(text))
    ]


def resolve_employee(db: Session, employee_id: str, name: str) -> User | None:
    """Match by 工号 first; fall back to 姓名 when 工号 is absent/not found."""
    if employee_id:
        user = db.scalars(select(User).where(User.employee_id == employee_id)).first()
        if user:
            return user
    if name:
        user = db.scalars(select(User).where(User.name == name)).first()
        if user:
            return user
    return None


# ---------------------------------------------------------------- employees

def import_employees(db: Session, text: str, lang: str = DEFAULT_LANG) -> str:
    """Columns: employee_id,name,email,bg,department,job_title,manager_id,role,password(optional)"""
    t = Translator(lang)
    created = updated = 0
    pending_manager: list[tuple[User, str]] = []
    for row in _rows(text):
        if not (row.get("employee_id") or row.get("name")):
            continue
        user = resolve_employee(db, row.get("employee_id"), row.get("name"))
        if user is None:
            if not row.get("employee_id"):
                continue  # cannot create a user without a 工号
            user = User(employee_id=row["employee_id"],
                        password_hash=hash_password(row.get("password") or row["employee_id"]))
            db.add(user)
            created += 1
        else:
            if row.get("password"):
                user.password_hash = hash_password(row["password"])
            updated += 1
        user.name = row.get("name") or user.name or row.get("employee_id")
        if row.get("email"):
            user.email = row["email"]
        if row.get("bg"):
            user.bg = row["bg"]
        if row.get("department"):
            user.department = row["department"]
        if row.get("job_title"):
            user.job_title = row["job_title"]
        if row.get("role"):
            user.role = row["role"].upper()
        if row.get("manager_id"):
            pending_manager.append((user, row["manager_id"]))
        user.updated_at = utcnow()
    db.flush()
    linked = 0
    for user, manager_ext in pending_manager:
        manager = resolve_employee(db, manager_ext, None)
        if manager:
            user.manager_id = manager.id
            linked += 1
    db.commit()
    return t.t("msg_emp_import", c=created, u=updated, l=linked)


# ---------------------------------------------------------------- plans (versioned)

def import_plans(db: Session, text: str, lang: str = DEFAULT_LANG) -> str:
    """Columns: period,employee_id,name,plan_name,kpi_name,weight_pct,quota,curve_name
    同一 (期间,员工, plan_name) 的多个 KPI 行构成一个计划；重复导入生成新版本。"""
    t = Translator(lang)
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    errors: list[str] = []
    for row in _rows(text):
        period = row.get("period")
        kpi_name = row.get("kpi_name")
        if not (period and kpi_name):
            continue
        employee = resolve_employee(db, row.get("employee_id"), row.get("name"))
        if employee is None:
            errors.append(f"{period}/{row.get('employee_id') or row.get('name')}: {t.t('row_no_employee')}")
            continue
        curve = db.scalars(select(Curve).where(Curve.name == row.get("curve_name"))).first()
        if curve is None:
            errors.append(f"{period}/{kpi_name}: {t.t('err_curve_missing', name=row.get('curve_name'))}")
            continue
        plan_name = (row.get("plan_name") or "DEFAULT").strip()
        key = (period, employee.id, plan_name)
        if key not in groups:
            groups[key] = {"kpis": []}
            order.append(key)
        groups[key]["kpis"].append(
            {"kpi_name": kpi_name, "weight_pct": float(row["weight_pct"]),
             "quota": float(row["quota"]), "curve_id": curve.id}
        )

    added = skipped = 0
    for key in order:
        period, emp_id, plan_name = key
        employee = db.get(User, emp_id)
        if is_locked(db, period, employee.bg):
            skipped += len(groups[key]["kpis"])
            continue
        # deactivate previous current version
        old = db.scalars(
            select(BonusPlan).where(
                BonusPlan.period == period, BonusPlan.employee_id == emp_id,
                BonusPlan.plan_name == plan_name, BonusPlan.is_current == True,  # noqa: E712
            )
        ).all()
        all_versions = db.scalars(
            select(BonusPlan.version).where(
                BonusPlan.period == period, BonusPlan.employee_id == emp_id,
                BonusPlan.plan_name == plan_name,
            )
        ).all()
        max_version = max(all_versions, default=0)
        for o in old:
            o.is_current = False
        plan = BonusPlan(period=period, employee_id=emp_id, plan_name=plan_name,
                         version=max_version + 1, is_current=True, imported_at=utcnow())
        db.add(plan)
        db.flush()
        for k in groups[key]["kpis"]:
            db.add(PlanKpi(plan_id=plan.id, **k))
        added += len(groups[key]["kpis"])
    db.commit()
    msg = t.t("msg_plans_imported", n=added)
    if skipped:
        msg += t.t("msg_sealed_skipped", n=skipped)
    if errors:
        msg += t.t("msg_errors", e="; ".join(errors[:5]))
    return msg


# ---------------------------------------------------------------- actuals (versioned)

def import_actuals(db: Session, text: str, lang: str = DEFAULT_LANG) -> str:
    """Columns: period,employee_id,name,kpi_name,actual (实绩为 YTD 累计值)。"""
    t = Translator(lang)
    added = skipped = 0
    errors: list[str] = []
    for row in _rows(text):
        period, kpi_name = row.get("period"), row.get("kpi_name")
        if not (period and kpi_name and row.get("actual")):
            continue
        employee = resolve_employee(db, row.get("employee_id"), row.get("name"))
        if employee is None:
            errors.append(f"{period}/{row.get('employee_id') or row.get('name')}: {t.t('row_no_employee')}")
            continue
        if is_locked(db, period, employee.bg):
            skipped += 1
            continue
        versions = db.scalars(
            select(Actual).where(
                Actual.period == period, Actual.employee_id == employee.id, Actual.kpi_name == kpi_name
            )
        ).all()
        for v in versions:
            v.is_current = False
        max_version = max((v.version for v in versions), default=0)
        db.add(Actual(period=period, employee_id=employee.id, kpi_name=kpi_name,
                      actual=float(row["actual"]), version=max_version + 1,
                      is_current=True, imported_at=utcnow()))
        added += 1
    db.commit()
    msg = t.t("msg_actuals_imported", n=added)
    if skipped:
        msg += t.t("msg_sealed_skipped", n=skipped)
    if errors:
        msg += t.t("msg_errors", e="; ".join(errors[:5]))
    return msg


# ---------------------------------------------------------------- soft delete via CSV

ACTUAL_DELETE_HEADER = ["period", "employee_id", "name", "kpi_name", "actual", "version",
                        "imported_at", "action", "reason"]
PLAN_DELETE_HEADER = ["period", "employee_id", "name", "plan_name", "version",
                      "imported_at", "action", "reason"]


def actual_delete_template_rows(db: Session) -> list[list]:
    rows = [ACTUAL_DELETE_HEADER]
    actuals = db.scalars(
        select(Actual).where(Actual.is_current == True, Actual.is_deleted == False)  # noqa: E712
        .order_by(Actual.period, Actual.employee_id)
    ).all()
    for a in actuals:
        emp = db.get(User, a.employee_id)
        rows.append([a.period, emp.employee_id, emp.name, a.kpi_name, f"{a.actual:g}",
                     a.version, a.imported_at.strftime("%Y-%m-%d %H:%M"), "", ""])
    return rows


def plan_delete_template_rows(db: Session) -> list[list]:
    rows = [PLAN_DELETE_HEADER]
    plans = db.scalars(
        select(BonusPlan).where(BonusPlan.is_current == True, BonusPlan.is_deleted == False)  # noqa: E712
        .order_by(BonusPlan.period, BonusPlan.employee_id)
    ).all()
    for p in plans:
        emp = db.get(User, p.employee_id)
        rows.append([p.period, emp.employee_id, emp.name, p.plan_name,
                     p.version, p.imported_at.strftime("%Y-%m-%d %H:%M"), "", ""])
    return rows


def _is_delete_mark(value: str) -> bool:
    return value.strip().upper() in ("DELETE", "删除", "DEL", "Y")


def apply_deletions(db: Session, text: str, entity: str, admin: User,
                    lang: str = DEFAULT_LANG) -> str:
    """Soft-delete records marked with action=DELETE. Reason is mandatory and logged."""
    t = Translator(lang)
    deleted = skipped_locked = missing = no_reason = 0
    for row in _rows(text):
        if not _is_delete_mark(row.get("action", "")):
            continue
        period = row.get("period")
        employee = resolve_employee(db, row.get("employee_id"), row.get("name"))
        if employee is None or not period:
            missing += 1
            continue
        reason = row.get("reason", "").strip()
        if entity == "actual":
            kpi_name = row.get("kpi_name")
            version = int(row.get("version") or 0)
            target = db.scalars(
                select(Actual).where(
                    Actual.period == period, Actual.employee_id == employee.id,
                    Actual.kpi_name == kpi_name, Actual.version == version,
                )
            ).first()
            ref = f"{period}/{employee.employee_id}/{kpi_name} v{version}"
        else:  # plan
            plan_name = (row.get("plan_name") or "DEFAULT").strip()
            version = int(row.get("version") or 0)
            target = db.scalars(
                select(BonusPlan).where(
                    BonusPlan.period == period, BonusPlan.employee_id == employee.id,
                    BonusPlan.plan_name == plan_name, BonusPlan.version == version,
                )
            ).first()
            ref = f"{period}/{employee.employee_id}/{plan_name} v{version}"
        if target is None:
            missing += 1
            continue
        if is_locked(db, period, employee.bg):
            skipped_locked += 1
            continue
        if not reason:
            no_reason += 1
            continue
        target.is_deleted = True
        target.is_current = False
        db.add(DataOpLog(op_type="DELETE", entity=entity, entity_ref=ref,
                         reason=reason, created_by=admin.id))
        deleted += 1
    db.commit()
    msg = t.t("msg_deleted", n=deleted)
    if missing:
        msg += t.t("msg_missing", n=missing)
    if skipped_locked:
        msg += t.t("msg_locked_skipped", n=skipped_locked)
    if no_reason:
        msg += t.t("msg_no_reason", n=no_reason)
    return msg


def deletion_logs(db: Session) -> list[DataOpLog]:
    return list(db.scalars(
        select(DataOpLog).where(DataOpLog.op_type == "DELETE")
        .order_by(DataOpLog.created_at.desc(), DataOpLog.id.desc())
    ).all())


def _csv_rows_for_calc_template(db: Session) -> list[list]:
    """One row per current plan; admin fills action=计算 to trigger."""
    rows = [["period", "employee_id", "name", "plan_name", "action"]]
    plans = db.scalars(
        select(BonusPlan).where(BonusPlan.is_current == True, BonusPlan.is_deleted == False)  # noqa: E712
        .order_by(BonusPlan.period, BonusPlan.employee_id)
    ).all()
    for p in plans:
        emp = db.get(User, p.employee_id)
        rows.append([p.period, emp.employee_id, emp.name, p.plan_name, ""])
    return rows


# ---------------------------------------------------------------- batch adjustments via CSV

ADJUST_HEADER = ["period", "employee_id", "name", "adjustment_pct", "reason"]


def adjustment_template_rows(db: Session) -> list[list]:
    """One row per (employee, period) that currently has an active plan."""
    rows = [ADJUST_HEADER]
    plans = db.scalars(
        select(BonusPlan).where(BonusPlan.is_current == True, BonusPlan.is_deleted == False)  # noqa: E712
        .order_by(BonusPlan.period, BonusPlan.employee_id)
    ).all()
    seen: set[tuple] = set()
    for p in plans:
        emp = db.get(User, p.employee_id)
        key = (p.period, emp.id)
        if key in seen:
            continue
        seen.add(key)
        rows.append([p.period, emp.employee_id, emp.name, "", ""])
    return rows


def parse_adjustment_rows(db: Session, text: str, lang: str = DEFAULT_LANG) -> list[dict]:
    """Validate batch adjustment rows. Returns entries with a status for preview."""
    t = Translator(lang)
    out = []
    for row in _rows(text):
        if not (row.get("period") or row.get("employee_id") or row.get("name")):
            continue
        period = row.get("period")
        employee = resolve_employee(db, row.get("employee_id"), row.get("name"))
        entry = {
            "period": period,
            "emp_ext": row.get("employee_id") or row.get("name"),
            "employee": employee,
            "adjustment_pct": row.get("adjustment_pct"),
            "reason": row.get("reason", "").strip(),
            "status": t.t("row_ok"), "note": "", "ok": True,
        }
        try:
            entry["delta"] = float(row.get("adjustment_pct") or "")
        except ValueError:
            entry["delta"] = None
        if not period:
            entry.update(status=t.t("row_no_period"), note="period", ok=False)
        elif employee is None:
            entry.update(status=t.t("row_no_employee"), note="", ok=False)
        elif entry["delta"] is None:
            entry.update(status=t.t("row_bad_delta"), note="adjustment_pct", ok=False)
        elif not entry["reason"]:
            entry.update(status=t.t("row_no_reason"), note="reason", ok=False)
        elif is_locked(db, period, employee.bg):
            entry.update(status=t.t("row_sealed"), note=f"{period}/{employee.bg}", ok=False)
        else:
            entry["note"] = f"{employee.name} · {entry['delta']:+g}pp"
        out.append(entry)
    return out


# ---------------------------------------------------------------- labels (translations)

LABEL_HEADER = ["original", "zh", "en"]


def collect_originals(db: Session) -> list[str]:
    """Distinct DB field values that may need translation."""
    originals: set[str] = set()
    originals |= {v for v in db.scalars(select(User.bg).distinct()).all() if v}
    originals |= {v for v in db.scalars(select(User.department).distinct()).all() if v}
    originals |= {v for v in db.scalars(select(User.job_title).distinct()).all() if v}
    originals |= {v for v in db.scalars(select(Curve.name)).all() if v}
    originals |= {k for k in db.scalars(select(PlanKpi.kpi_name).distinct()).all() if k}
    originals |= {p for p in db.scalars(select(BonusPlan.plan_name).distinct()).all() if p}
    return sorted(originals)


def label_rows(db: Session) -> list[list]:
    """Template/export rows: every known original with its current zh/en."""
    existing = {l.original: l for l in db.scalars(select(Label)).all()}
    known = collect_originals(db)
    rows = [LABEL_HEADER]
    for original in known + [o for o in existing if o not in known]:
        label = existing.get(original)
        rows.append([original, label.zh if label else "", label.en if label else ""])
    return rows


def import_labels(db: Session, text: str, admin: User, lang: str = DEFAULT_LANG) -> str:
    """Upsert Label rows keyed by original. Logs the operation."""
    t = Translator(lang)
    saved = 0
    for row in _rows(text):
        original = row.get("original", "").strip()
        if not original:
            continue
        label = db.scalars(select(Label).where(Label.original == original)).first()
        if label is None:
            label = Label(original=original)
            db.add(label)
        if row.get("zh"):
            label.zh = row["zh"]
        if row.get("en"):
            label.en = row["en"]
        saved += 1
    db.add(DataOpLog(op_type="IMPORT", entity="label", entity_ref=f"{saved} labels",
                     reason="CSV label upsert", created_by=admin.id))
    db.commit()
    invalidate_label_cache()
    return t.t("msg_labels_saved", n=saved)


# ---------------------------------------------------------------- export

def export_results_rows(db: Session, bg: str | None = None, period: str | None = None,
                        year: str | None = None) -> list[list]:
    """Latest run per period; rates only. Filterable by BG, exact period or year."""
    from .models import BonusResult, CalcRun

    periods = db.scalars(select(CalcRun.period).distinct()).all()
    if period:
        periods = [p for p in periods if p == period]
    if year:
        periods = [p for p in periods if p.split("-")[0] == year]
    header = ["period", "employee_id", "name", "bg", "department", "job_title", "plan_name",
              "unweighted_rate_pct", "weighted_rate_pct", "adjustment_pct", "final_rate_pct",
              "adjusted", "calculated_at"]
    rows = [header]
    for p in sorted(periods):
        run = db.scalars(
            select(CalcRun).where(CalcRun.period == p).order_by(CalcRun.created_at.desc(), CalcRun.id.desc())
        ).first()
        if not run:
            continue
        for r in db.scalars(select(BonusResult).where(BonusResult.run_id == run.id)).all():
            emp = r.employee
            if bg and emp.bg != bg:
                continue
            rows.append([p, emp.employee_id, emp.name, emp.bg, emp.department or "",
                         emp.job_title or "", r.plan_name,
                         f"{r.unweighted_rate_pct:.2f}", f"{r.weighted_rate_pct:.2f}",
                         f"{r.adjustment_pct:.2f}", f"{r.final_rate_pct:.2f}",
                         "Y" if r.adjusted else "", run.created_at.strftime("%Y-%m-%d %H:%M")])
    return rows


def to_csv(rows: list[list]) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()
