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
import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .calc import is_locked
from .deps import apply_managed_bgs, archive_user_info, bg_allowed, current_info_tuple
from .i18n import DEFAULT_LANG, Translator, invalidate_label_cache
from .models import Actual, BonusPlan, Curve, DataOpLog, Label, PlanKpi, User, UserManagedBg
from .security import hash_password


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _bg_in(emp_bg: str | None, bg) -> bool:
    """Match an employee's BG against a scope that may be None (all), a single BG, or a
    collection of BGs (a BG_ADMIN who administers several — feature #4)."""
    if not bg:
        return True
    if isinstance(bg, (set, frozenset, list, tuple)):
        return emp_bg in bg
    return emp_bg == bg


def _split_bgs(bg_field: str) -> list[str]:
    """Split a BG cell that may list several administered BGs (feature #4: a BG_ADMIN can
    own multiple BGs). Separators: / | 、 ; . Returns an ordered, de-duplicated list."""
    out: list[str] = []
    for part in re.split(r"[/|、;；]", bg_field or ""):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


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


# ---------------------------------------------------------------- unified quarterly big-table import
#
# One sheet carries EVERYTHING needed for a quarter's YTD calculation:
#   period,employee_id,name,email,bg,department,job_title,manager_id,role,
#   plan_name,kpi_name,weight_pct,quota,curve_name[,actual]
# The letter-data sheet uses the same columns minus `actual`.
#
# Validation per row: user exists / curve exists / duplicate person+KPI in sheet /
# missing required fields / sealed quarter / (BG admins) out-of-BG rows.
# Rows whose data is fully identical to the current system data are IGNORED (not errors).

def big_header(with_actual: bool = True) -> list[str]:
    cols = ["period", "employee_id", "name", "email", "bg", "department", "job_title",
            "manager_id", "role", "plan_name", "kpi_name", "weight_pct", "quota", "curve_name"]
    if with_actual:
        cols.append("actual")
    return cols


BIG_HEADER = big_header(True)
LETTER_DATA_HEADER = big_header(False)


def recent_periods(db: Session, n: int = 3) -> list[str]:
    """The most recent n distinct periods known to the system (template prefill choices)."""
    periods = set(db.scalars(select(BonusPlan.period).distinct()).all())
    periods |= set(db.scalars(select(Actual.period).distinct()).all())
    return sorted(periods, reverse=True)[:n]


def big_template_rows(db: Session, period: str | None = None, bg: str | None = None,
                      with_actual: bool = True) -> list[list]:
    """Import template. No period → header only (blank template). With period →
    prefilled from that quarter's current data, scoped to bg (permission filter)."""
    header = big_header(with_actual)
    rows = [header]
    if not period:
        return rows
    plans = db.scalars(
        select(BonusPlan).where(BonusPlan.period == period,
                                BonusPlan.is_current == True,  # noqa: E712
                                BonusPlan.is_deleted == False)  # noqa: E712
        .order_by(BonusPlan.employee_id, BonusPlan.plan_name)
    ).all()
    for p in plans:
        emp = db.get(User, p.employee_id)
        if not _bg_in(emp.bg, bg):
            continue
        mgr = db.get(User, emp.manager_id) if emp.manager_id else None
        for kpi in p.kpis:
            actual = ""
            if with_actual:
                a = db.scalars(
                    select(Actual).where(Actual.period == period, Actual.employee_id == emp.id,
                                         Actual.kpi_name == kpi.kpi_name,
                                         Actual.is_current == True,  # noqa: E712
                                         Actual.is_deleted == False)  # noqa: E712
                ).first()
                actual = fmt_num(a.actual) if a else ""
            rows.append([period, emp.employee_id, emp.name, emp.email or "", emp.bg or "",
                         emp.department or "", emp.job_title or "",
                         mgr.employee_id if mgr else "", emp.role or "",
                         p.plan_name, kpi.kpi_name, fmt_num(kpi.weight_pct), fmt_num(kpi.quota),
                         kpi.curve.name, actual])
    return rows


def _num(value) -> float | None:
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def fmt_num(value) -> str:
    """Human/CSV-friendly number: no scientific notation, whole numbers as ints,
    otherwise up to 4 decimals with trailing zeros trimmed."""
    if value is None or value == "":
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f.is_integer():
        return str(int(f))
    return f"{f:.4f}".rstrip("0").rstrip(".")


def _group_info_raw(rows: list[dict]) -> dict:
    """Merge employee-info columns across a plan group's rows.

    The big sheet only carries the info columns on a person's first row, but after
    the later-row-wins override (#7) the info-bearing row may not be the first valid
    row of the group. Take the first non-empty value per info field across the rows so
    an info update is detected no matter which row carries it.
    """
    info_fields = ("name", "email", "bg", "department", "job_title", "role", "manager_id")
    merged: dict = {}
    for field in info_fields:
        for r in rows:
            v = (r["raw"].get(field) or "").strip()
            if v:
                merged[field] = v
                break
    return merged


def _user_info_changes(db: Session, employee: User, raw: dict, actor: User) -> dict:
    """Employee-info fields provided in the row that differ from the current record."""
    changes: dict = {}
    for field in ("name", "email", "bg", "department", "job_title"):
        v = (raw.get(field) or "").strip()
        if v and v != (getattr(employee, field) or ""):
            changes[field] = v
    role = (raw.get("role") or "").strip().upper()
    if role and actor.role == "ADMIN" and role != employee.role:
        changes["role"] = role
    mgr_ext = (raw.get("manager_id") or "").strip()
    if mgr_ext:
        mgr = resolve_employee(db, mgr_ext, "")
        if mgr and mgr.id != employee.manager_id:
            changes["manager"] = mgr.id
    return changes


def parse_big_rows(db: Session, text: str, actor: User, lang: str = DEFAULT_LANG,
                   with_actual: bool = True) -> list[dict]:
    """Pass-1 validation of the unified sheet. Each entry carries ok/ignored flags
    and a translated status for the preview table."""
    t = Translator(lang)
    entries: list[dict] = []
    by_key: dict[tuple, int] = {}
    for raw in _rows(text):
        if not any((raw.get(c) or "").strip() for c in ("period", "employee_id", "name", "kpi_name")):
            continue
        period = (raw.get("period") or "").strip()
        plan_name = (raw.get("plan_name") or "").strip()
        kpi_name = (raw.get("kpi_name") or "").strip()
        curve_name = (raw.get("curve_name") or "").strip()
        employee = resolve_employee(db, raw.get("employee_id", ""), raw.get("name", ""))
        entry = {
            "raw": raw, "period": period, "employee": employee,
            "emp_ext": (raw.get("employee_id") or raw.get("name") or "?").strip(),
            "plan_name": plan_name, "kpi_name": kpi_name, "curve_name": curve_name,
            "weight": _num(raw.get("weight_pct")), "quota": _num(raw.get("quota")),
            "actual": _num(raw.get("actual")) if with_actual else None,
            "curve_id": None, "status": "", "note": "", "ok": False, "ignored": False,
        }
        idx = len(entries)
        entries.append(entry)
        if not period:
            entry["status"] = t.t("row_no_period"); continue
        if employee is None:
            entry["status"] = t.t("row_no_employee"); continue
        if actor.role == "BG_ADMIN" and not bg_allowed(actor, employee.bg):
            entry["status"] = t.t("row_out_of_bg"); continue
        if is_locked(db, period, employee.bg):
            entry["status"] = t.t("row_sealed"); entry["note"] = f"{period}/{employee.bg}"; continue
        # Same period+employee+plan+KPI appearing again -> the LATER row overrides the
        # earlier one (before sealing). Mark the previous occurrence as superseded.
        key = (period, employee.id, plan_name, kpi_name)
        if key in by_key:
            prev = entries[by_key[key]]
            if prev["ok"]:
                prev.update(ok=False, ignored=True, status=t.t("row_overwritten"))
        by_key[key] = idx
        missing = [f for f, v in (("plan_name", plan_name), ("kpi_name", kpi_name),
                                  ("curve_name", curve_name),
                                  ("weight_pct", (raw.get("weight_pct") or "").strip()),
                                  ("quota", (raw.get("quota") or "").strip())) if not v]
        if with_actual and not (raw.get("actual") or "").strip():
            missing.append("actual")
        if missing:
            entry["status"] = t.t("row_missing_fields", f=", ".join(missing)); continue
        bad = [f for f, v in (("weight_pct", entry["weight"]), ("quota", entry["quota"])) if v is None]
        if with_actual and entry["actual"] is None:
            bad.append("actual")
        if bad:
            entry["status"] = t.t("row_bad_number", f=", ".join(bad)); continue
        if entry["quota"] <= 0:
            entry["status"] = t.t("row_bad_number", f="quota"); continue
        curve = db.scalars(select(Curve).where(Curve.name == curve_name)).first()
        if curve is None:
            entry["status"] = t.t("row_no_curve", name=curve_name); continue
        entry["curve_id"] = curve.id
        entry["status"] = t.t("row_importable")
        entry["ok"] = True
    _mark_identical_groups(db, entries, actor, t, with_actual)
    return entries


def _current_actual(db: Session, period: str, emp_id: int, kpi_name: str) -> Actual | None:
    return db.scalars(
        select(Actual).where(Actual.period == period, Actual.employee_id == emp_id,
                             Actual.kpi_name == kpi_name,
                             Actual.is_current == True,  # noqa: E712
                             Actual.is_deleted == False)  # noqa: E712
    ).first()


def _mark_identical_groups(db: Session, entries: list[dict], actor: User,
                           t: Translator, with_actual: bool) -> None:
    """A plan group whose sheet data fully matches the system (KPI set, weights,
    quotas, curves, actuals, employee info) is ignored — not an error, no new version."""
    groups: dict[tuple, list[dict]] = {}
    for e in entries:
        if e["ok"]:
            groups.setdefault((e["period"], e["employee"].id, e["plan_name"]), []).append(e)
    for (period, emp_id, plan_name), rows in groups.items():
        plan = db.scalars(
            select(BonusPlan).where(BonusPlan.period == period, BonusPlan.employee_id == emp_id,
                                    BonusPlan.plan_name == plan_name,
                                    BonusPlan.is_current == True,  # noqa: E712
                                    BonusPlan.is_deleted == False)  # noqa: E712
        ).first()
        if plan is None:
            continue  # new plan → importable
        current = {k.kpi_name: (round(k.weight_pct, 6), round(k.quota, 6), k.curve_id)
                   for k in plan.kpis}
        sheet = {e["kpi_name"]: (round(e["weight"], 6), round(e["quota"], 6), e["curve_id"])
                 for e in rows}
        if current != sheet:
            continue
        identical = True
        if with_actual:
            for e in rows:
                a = _current_actual(db, period, emp_id, e["kpi_name"])
                if a is None or abs(a.actual - e["actual"]) > 1e-9:
                    identical = False
                    break
        employee = db.get(User, emp_id)
        if identical and not _user_info_changes(db, employee, _group_info_raw(rows), actor):
            for e in rows:
                e.update(ok=False, ignored=True, status=t.t("row_identical"))


def big_summary(entries: list[dict]) -> dict:
    return {"ok": sum(1 for e in entries if e["ok"]),
            "ignored": sum(1 for e in entries if e["ignored"]),
            "errors": sum(1 for e in entries if not e["ok"] and not e["ignored"])}


def execute_big_import(db: Session, text: str, actor: User, lang: str = DEFAULT_LANG,
                       with_actual: bool = True, proxy_note: str = "") -> str:
    """Pass-2: re-parse and import the valid rows. Identical rows are ignored,
    invalid rows are skipped (they were reported in the preview)."""
    t = Translator(lang)
    entries = parse_big_rows(db, text, actor, lang, with_actual)
    summary = big_summary(entries)
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for e in entries:
        if not e["ok"]:
            continue
        key = (e["period"], e["employee"].id, e["plan_name"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)
    plans = kpis = actuals = users = 0
    for period, emp_id, plan_name in order:
        rows = groups[(period, emp_id, plan_name)]
        employee = db.get(User, emp_id)
        changes = _user_info_changes(db, employee, _group_info_raw(rows), actor)
        if changes:
            archive_user_info(db, employee, actor)
            for field, value in changes.items():
                if field == "manager":
                    employee.manager_id = value
                else:
                    setattr(employee, field, value)
            employee.updated_at = utcnow()
            users += 1
        # the sheet fully defines the plan's KPI set → new version replaces it
        old = db.scalars(select(BonusPlan).where(
            BonusPlan.period == period, BonusPlan.employee_id == emp_id,
            BonusPlan.plan_name == plan_name,
            BonusPlan.is_current == True)).all()  # noqa: E712
        max_version = max(db.scalars(select(BonusPlan.version).where(
            BonusPlan.period == period, BonusPlan.employee_id == emp_id,
            BonusPlan.plan_name == plan_name)).all(), default=0)
        for o in old:
            o.is_current = False
        plan = BonusPlan(period=period, employee_id=emp_id, plan_name=plan_name,
                         version=max_version + 1, is_current=True, imported_at=utcnow())
        db.add(plan)
        db.flush()
        for e in rows:
            db.add(PlanKpi(plan_id=plan.id, kpi_name=e["kpi_name"], weight_pct=e["weight"],
                           quota=e["quota"], curve_id=e["curve_id"]))
        plans += 1
        kpis += len(rows)
        db.add(DataOpLog(op_type="IMPORT", entity="plan",
                         entity_ref=f"{period}/{employee.employee_id}/{plan_name} v{plan.version}",
                         reason="quarter sheet import" + (f" ({proxy_note})" if proxy_note else ""),
                         created_by=actor.id))
        if with_actual:
            for e in rows:
                versions = db.scalars(select(Actual).where(
                    Actual.period == period, Actual.employee_id == emp_id,
                    Actual.kpi_name == e["kpi_name"])).all()
                current = next((v for v in versions if v.is_current and not v.is_deleted), None)
                if current is not None and abs(current.actual - e["actual"]) <= 1e-9:
                    continue
                for v in versions:
                    v.is_current = False
                db.add(Actual(period=period, employee_id=emp_id, kpi_name=e["kpi_name"],
                              actual=e["actual"],
                              version=max((v.version for v in versions), default=0) + 1,
                              is_current=True, imported_at=utcnow()))
                actuals += 1
    db.commit()
    return t.t("msg_big_import", p=plans, k=kpis, a=actuals, u=users,
               i=summary["ignored"], e=summary["errors"])


def big_error_rows(db: Session, text: str, actor: User, lang: str = DEFAULT_LANG,
                   with_actual: bool = True) -> list[list]:
    """Error list CSV: the offending rows plus status/note columns, so the user can
    fix them and re-upload."""
    entries = parse_big_rows(db, text, actor, lang, with_actual)
    header = big_header(with_actual) + ["status", "note"]
    rows = [header]
    for e in entries:
        if e["ok"] or e["ignored"]:
            continue
        raw = e["raw"]
        rows.append([(raw.get(c) or "") for c in big_header(with_actual)]
                    + [e["status"], e["note"]])
    return rows


# ---------------------------------------------------------------- year-based letter-data import
#
# Feature #10: the letter-data sheet uses a YEAR-shaped template — one row per
# (year, employee, plan, KPI) carrying FOUR YTD quota columns (ytd_q1..ytd_q4).
# Internally we expand each row into up to four big-table rows (period =
# f"{year}-Q{n}", quota = ytd_qn) so the existing big-table parser, latest-wins
# logic and versioned BonusPlan upsert all apply unchanged. Empty ytd_qN cells
# are skipped (no plan is created for that quarter).

YEAR_HEADER = ["year", "employee_id", "name", "email", "bg", "department", "job_title",
               "manager_id", "role", "plan_name", "kpi_name", "weight_pct", "curve_name",
               "ytd_q1", "ytd_q2", "ytd_q3", "ytd_q4"]
QUARTER_SUFFIXES = ["Q1", "Q2", "Q3", "Q4"]


def recent_years(db: Session, n: int = 3) -> list[str]:
    """Distinct years that have any BonusPlan/Actual data, most recent first."""
    periods = set(db.scalars(select(BonusPlan.period).distinct()).all())
    periods |= set(db.scalars(select(Actual.period).distinct()).all())
    years = sorted({p.split("-")[0] for p in periods if "-" in p}, reverse=True)
    return years[:n]


def year_to_big_text(text: str) -> str:
    """Expand a year-shaped letter-data CSV into the (period-keyed) big-table
    format that parse_big_rows / execute_big_import already understand. Non-year
    headers pass through unchanged so callers can feed either flavor."""
    rows = _rows(text)
    if not rows:
        return text
    first = next(iter(rows[0].keys()), "")
    # Already big-shaped? Leave untouched.
    if "period" in rows[0] and "year" not in rows[0]:
        return text
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(big_header(False))   # same columns as LETTER_DATA_HEADER
    for row in rows:
        year = (row.get("year") or "").strip()
        if not year:
            continue
        base = [
            year,                                                    # period slot
            (row.get("employee_id") or "").strip(),
            (row.get("name") or "").strip(),
            (row.get("email") or "").strip(),
            (row.get("bg") or "").strip(),
            (row.get("department") or "").strip(),
            (row.get("job_title") or "").strip(),
            (row.get("manager_id") or "").strip(),
            (row.get("role") or "").strip(),
            (row.get("plan_name") or "").strip(),
            (row.get("kpi_name") or "").strip(),
            (row.get("weight_pct") or "").strip(),
            "",                                                       # quota filled per quarter below
            (row.get("curve_name") or "").strip(),
        ]
        for qi, q in enumerate(QUARTER_SUFFIXES):
            quota = (row.get(f"ytd_q{qi+1}") or "").strip()
            if quota == "":
                continue
            r = list(base)
            r[0] = f"{year}-{q}"
            r[12] = quota
            writer.writerow(r)
    return out.getvalue()


def year_letter_template_rows(db: Session, year: str | None = None,
                              bg=None) -> list[list]:
    """Prefill a year-form sheet from existing per-quarter BonusPlans: group by
    (year, employee, plan_name, kpi_name) and lay the four YTD quotas side by side.
    Weight / curve come from the latest current plan version."""
    rows = [YEAR_HEADER[:]]
    if not year:
        return rows
    stmt = select(BonusPlan).where(BonusPlan.period.like(f"{year}-%"),
                                   BonusPlan.is_current == True,  # noqa: E712
                                   BonusPlan.is_deleted == False)  # noqa: E712
    plans = db.scalars(stmt).all()
    grouped: dict[tuple, dict] = {}
    order: list[tuple] = []
    for p in plans:
        emp = db.get(User, p.employee_id)
        if not emp or not _bg_in(emp.bg, bg):
            continue
        try:
            qi = QUARTER_SUFFIXES.index(p.period.split("-")[1])
        except (ValueError, IndexError):
            continue
        for kpi in p.kpis:
            key = (year, emp.employee_id, p.plan_name, kpi.kpi_name)
            if key not in grouped:
                grouped[key] = {
                    "emp": emp, "plan_name": p.plan_name, "kpi_name": kpi.kpi_name,
                    "weight": kpi.weight_pct, "curve": kpi.curve.name if kpi.curve else "",
                    "ytd": ["", "", "", ""],
                }
                order.append(key)
            g = grouped[key]
            g["ytd"][qi] = fmt_num(kpi.quota)
            g["weight"] = kpi.weight_pct
            g["curve"] = kpi.curve.name if kpi.curve else ""
    for key in order:
        g = grouped[key]
        emp = g["emp"]
        mgr = db.get(User, emp.manager_id) if emp.manager_id else None
        rows.append([
            year, emp.employee_id, emp.name, emp.email or "", emp.bg or "",
            emp.department or "", emp.job_title or "",
            mgr.employee_id if mgr else "", emp.role or "",
            g["plan_name"], g["kpi_name"], fmt_num(g["weight"]), g["curve"],
            *g["ytd"],
        ])
    return rows


def parse_year_letter_rows(db: Session, text: str, actor: User, lang: str = DEFAULT_LANG) -> list[dict]:
    """Parse a year-form sheet by first expanding it into the big-table format, then
    delegating to parse_big_rows. This keeps the error vocabulary (BG scope, curve,
    required, latest-wins) identical between the two letter/calculation sheets."""
    return parse_big_rows(db, year_to_big_text(text), actor, lang, with_actual=False)


def execute_year_letter_import(db: Session, text: str, actor: User, lang: str = DEFAULT_LANG,
                               proxy_note: str = "") -> str:
    return execute_big_import(db, year_to_big_text(text), actor, lang, with_actual=False,
                              proxy_note=proxy_note)


def year_letter_error_rows(db: Session, text: str, actor: User, lang: str = DEFAULT_LANG) -> list[list]:
    """Error-list CSV keyed by the ORIGINAL year-form row so the user can fix and
    re-upload the same sheet they sent us. Big-table errors (from the expanded
    view) are mapped back to (year, employee, plan, kpi)."""
    expanded = year_to_big_text(text)
    entries = parse_big_rows(db, expanded, actor, lang, with_actual=False)
    header = YEAR_HEADER + ["status", "note"]
    rows = [header]
    original_year_rows = _rows(text)
    # Group big-table entries by (year, employee, plan, kpi) so a single year row
    # can carry a merged error/warning string.
    grouped: dict[tuple, list[dict]] = {}
    for e in entries:
        if e["ok"] or e["ignored"]:
            continue
        raw = e["raw"]
        year = (raw.get("period") or "").split("-")[0]
        key = (year, raw.get("employee_id") or "", raw.get("plan_name") or "", raw.get("kpi_name") or "")
        grouped.setdefault(key, []).append(e)
    for orow in original_year_rows:
        year = (orow.get("year") or "").strip()
        if not year:
            continue
        key = (year, (orow.get("employee_id") or "").strip(),
               (orow.get("plan_name") or "").strip(), (orow.get("kpi_name") or "").strip())
        errs = grouped.get(key)
        if not errs:
            continue
        seen = set()
        merged_status, merged_note = [], []
        for e in errs:
            if e["status"] not in seen:
                merged_status.append(e["status"])
                seen.add(e["status"])
            if e["note"] and e["note"] not in merged_note:
                merged_note.append(e["note"])
        out = [orow.get(h, "") or "" for h in YEAR_HEADER]
        rows.append(out + [" / ".join(merged_status), "; ".join(merged_note)])
    return rows


# ---------------------------------------------------------------- batch user import (ADMIN only)
#
# A dedicated roster sheet for user management. Idempotent upsert semantics:
#   * employee_id not in the system  -> CREATE (password defaults to employee_id)
#   * employee_id exists, fields differ -> UPDATE the changed fields
#   * employee_id exists, fully identical -> IGNORED (not an error)
# Validation: required fields / valid role / in-sheet duplicate id or email /
# email taken by a different employee_id / manager must already exist.

USER_HEADER = ["employee_id", "name", "email", "role", "bg", "department",
               "job_title", "manager_id", "password"]
VALID_ROLES = {"ADMIN", "BG_ADMIN", "MANAGER", "EMPLOYEE"}


def user_template_rows() -> list[list]:
    """Blank batch-user template (header only)."""
    return [USER_HEADER]


def _user_field_changes(db: Session, existing: User, raw: dict) -> dict:
    """Fields present in the row that differ from the current user record.

    BG handling is role-aware (feature #4): a BG_ADMIN may administer several BGs, so
    their BG cell is parsed as a list and compared against the current managed-BG set
    (stored under a "bgs" key); everyone else keeps a single home BG ("bg" key)."""
    changes: dict = {}
    for field in ("name", "email", "department", "job_title"):
        v = (raw.get(field) or "").strip()
        if v and v != (getattr(existing, field) or ""):
            changes[field] = v
    role = (raw.get("role") or "").strip().upper()
    if role and role != existing.role:
        changes["role"] = role
    effective_role = role or existing.role
    bg_field = (raw.get("bg") or "").strip()
    if bg_field:
        if effective_role == "BG_ADMIN":
            new_bgs = _split_bgs(bg_field)
            if new_bgs and set(new_bgs) != existing.bg_scope:
                changes["bgs"] = new_bgs
        elif bg_field != (existing.bg or ""):
            changes["bg"] = bg_field
    mgr_ext = (raw.get("manager_id") or "").strip()
    if mgr_ext:
        mgr = resolve_employee(db, mgr_ext, "")
        if mgr and mgr.id != existing.manager_id:
            changes["manager"] = mgr.id
    return changes


def parse_user_rows(db: Session, text: str, lang: str = DEFAULT_LANG) -> list[dict]:
    """Pass-1 validation of the batch-user roster. Each entry carries ok/ignored flags,
    an action ('create'/'update') and a translated status for the preview table."""
    t = Translator(lang)
    entries: list[dict] = []
    seen_ids: set[str] = set()
    seen_emails: set[str] = set()
    for raw in _rows(text):
        emp_id = (raw.get("employee_id") or "").strip()
        name = (raw.get("name") or "").strip()
        email = (raw.get("email") or "").strip()
        if not (emp_id or name or email):
            continue
        role = (raw.get("role") or "").strip().upper() or "EMPLOYEE"
        entry = {
            "raw": raw, "employee_id": emp_id, "name": name, "email": email, "role": role,
            "bg": (raw.get("bg") or "").strip(), "department": (raw.get("department") or "").strip(),
            "job_title": (raw.get("job_title") or "").strip(),
            "manager_ext": (raw.get("manager_id") or "").strip(),
            "existing": None, "changes": {}, "action": "",
            "status": "", "note": "", "ok": False, "ignored": False,
        }
        entries.append(entry)
        missing = [f for f, v in (("employee_id", emp_id), ("name", name), ("email", email)) if not v]
        if missing:
            entry["status"] = t.t("row_missing_fields", f=", ".join(missing)); continue
        if role not in VALID_ROLES:
            entry["status"] = t.t("row_invalid_role", role=role); continue
        if emp_id in seen_ids or email in seen_emails:
            entry["status"] = t.t("row_user_dup"); continue
        seen_ids.add(emp_id)
        seen_emails.add(email)
        existing = db.scalars(select(User).where(User.employee_id == emp_id)).first()
        by_email = db.scalars(select(User).where(User.email == email)).first()
        if by_email and (existing is None or by_email.id != existing.id):
            entry["status"] = t.t("row_email_taken", email=email); continue
        entry["existing"] = existing
        if existing is None:
            entry["action"] = "create"
            entry["status"] = t.t("row_user_create")
            entry["ok"] = True
        else:
            changes = _user_field_changes(db, existing, raw)
            entry["changes"] = changes
            if changes:
                entry["action"] = "update"
                entry["status"] = t.t("row_user_update")
                entry["note"] = ", ".join(sorted(changes))
                entry["ok"] = True
            else:
                entry["ignored"] = True
                entry["status"] = t.t("row_user_identical")
    return entries


def user_summary(entries: list[dict]) -> dict:
    return {"create": sum(1 for e in entries if e["ok"] and e["action"] == "create"),
            "update": sum(1 for e in entries if e["ok"] and e["action"] == "update"),
            "ignored": sum(1 for e in entries if e["ignored"]),
            "errors": sum(1 for e in entries if not e["ok"] and not e["ignored"])}


def execute_user_import(db: Session, text: str, actor: User, lang: str = DEFAULT_LANG,
                        proxy_note: str = "") -> str:
    """Pass-2: create/update the valid rows; identical and invalid rows are skipped.

    Managers are resolved in this order: existing DB user → a user created earlier in
    this same sheet → a platform ADMIN as a temporary proxy (logged). This lets a
    roster sheet define brand-new managers and reference them immediately.
    """
    t = Translator(lang)
    entries = parse_user_rows(db, text, lang)
    created_map: dict[str, User] = {}
    created = updated = mgr_proxied = 0

    def _admin_fallback() -> User | None:
        return db.scalars(select(User).where(User.role == "ADMIN",
                                             User.is_active == True)).first()  # noqa: E712

    # Pass 1: create new users (manager resolved in pass 2 so forward references work).
    for e in entries:
        if e["ok"] and e["action"] == "create":
            password = (e["raw"].get("password") or "").strip() or e["employee_id"]
            bgs = _split_bgs(e["bg"])
            if e["role"] == "BG_ADMIN":
                primary = bgs[0] if bgs else None
            else:
                primary = e["bg"] or None
            user = User(employee_id=e["employee_id"], name=e["name"], email=e["email"],
                        role=e["role"], bg=primary, department=e["department"] or None,
                        job_title=e["job_title"] or None, password_hash=hash_password(password))
            db.add(user)
            db.flush()
            if e["role"] == "BG_ADMIN":
                for b in bgs:
                    db.add(UserManagedBg(user_id=user.id, bg=b))
            created_map[e["employee_id"]] = user
            created += 1

    # Pass 2: apply field updates and resolve each manager.
    for e in entries:
        if not e["ok"]:
            continue
        note = f" ({proxy_note})" if proxy_note else ""
        is_create = e["action"] == "create"
        user = created_map.get(e["employee_id"]) or e["existing"]
        changed_fields: list[str] = []
        mgr_ext = e["manager_ext"]
        proxied = False
        if mgr_ext:
            mgr = resolve_employee(db, mgr_ext, "") or created_map.get(mgr_ext)
            if mgr is None:
                mgr = _admin_fallback()
                proxied = mgr is not None
                if proxied:
                    mgr_proxied += 1
            if mgr is not None and mgr.id != user.manager_id:
                user.manager_id = mgr.id
                changed_fields.append("manager")
        # Feature #4: archive the superseded (current) info before it is overwritten.
        if not is_create:
            archive_user_info(db, user, actor)
        for field, value in e["changes"].items():
            if field in ("manager", "bgs"):
                continue  # manager handled above; bgs handled below
            setattr(user, field, value)
            changed_fields.append(field)
        if "bgs" in e["changes"]:
            apply_managed_bgs(db, user, e["changes"]["bgs"])
            changed_fields.append("bg")
        if changed_fields:
            user.updated_at = utcnow()
        action_txt = ("create" if is_create
                      else "update " + ", ".join(sorted(set(changed_fields))))
        if proxied:
            action_txt += " [manager missing → admin proxy]"
        db.add(DataOpLog(op_type="IMPORT", entity="user", entity_ref=e["employee_id"],
                         reason=f"batch user import: {action_txt}" + note, created_by=actor.id))
        if not is_create:
            updated += 1
    db.commit()
    summary = user_summary(entries)
    return t.t("msg_users_import", c=created, u=updated, i=summary["ignored"], e=summary["errors"])


def user_error_rows(db: Session, text: str, lang: str = DEFAULT_LANG) -> list[list]:
    entries = parse_user_rows(db, text, lang)
    rows = [USER_HEADER + ["status", "note"]]
    for e in entries:
        if e["ok"] or e["ignored"]:
            continue
        raw = e["raw"]
        rows.append([(raw.get(c) or "") for c in USER_HEADER] + [e["status"], e["note"]])
    return rows


# ---------------------------------------------------------------- soft delete via CSV

ACTUAL_DELETE_HEADER = ["period", "employee_id", "name", "kpi_name", "actual", "version",
                        "imported_at", "action", "reason"]
PLAN_DELETE_HEADER = ["period", "employee_id", "name", "plan_name", "version",
                      "imported_at", "action", "reason"]


def actual_delete_template_rows(db: Session, period: str | None = None) -> list[list]:
    rows = [ACTUAL_DELETE_HEADER]
    stmt = select(Actual).where(Actual.is_current == True, Actual.is_deleted == False)  # noqa: E712
    if period:
        stmt = stmt.where(Actual.period == period)
    actuals = db.scalars(stmt.order_by(Actual.period, Actual.employee_id)).all()
    for a in actuals:
        emp = db.get(User, a.employee_id)
        rows.append([a.period, emp.employee_id, emp.name, a.kpi_name, fmt_num(a.actual),
                     a.version, a.imported_at.strftime("%Y-%m-%d %H:%M"), "", ""])
    return rows


def plan_delete_template_rows(db: Session, period: str | None = None) -> list[list]:
    rows = [PLAN_DELETE_HEADER]
    stmt = select(BonusPlan).where(BonusPlan.is_current == True, BonusPlan.is_deleted == False)  # noqa: E712
    if period:
        stmt = stmt.where(BonusPlan.period == period)
    plans = db.scalars(stmt.order_by(BonusPlan.period, BonusPlan.employee_id)).all()
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


def _csv_rows_for_calc_template(db: Session, period: str | None = None) -> list[list]:
    """One row per current plan; admin fills action=计算 to trigger."""
    rows = [["period", "employee_id", "name", "plan_name", "action"]]
    stmt = select(BonusPlan).where(BonusPlan.is_current == True, BonusPlan.is_deleted == False)  # noqa: E712
    if period:
        stmt = stmt.where(BonusPlan.period == period)
    plans = db.scalars(stmt.order_by(BonusPlan.period, BonusPlan.employee_id)).all()
    for p in plans:
        emp = db.get(User, p.employee_id)
        rows.append([p.period, emp.employee_id, emp.name, p.plan_name, ""])
    return rows


# ---------------------------------------------------------------- batch adjustments via CSV

ADJUST_HEADER = ["period", "employee_id", "name", "adjustment_pct", "reason"]


def adjustment_template_rows(db: Session, period: str | None = None) -> list[list]:
    """One row per (employee, period) that currently has an active plan."""
    rows = [ADJUST_HEADER]
    stmt = select(BonusPlan).where(BonusPlan.is_current == True, BonusPlan.is_deleted == False)  # noqa: E712
    if period:
        stmt = stmt.where(BonusPlan.period == period)
    plans = db.scalars(stmt.order_by(BonusPlan.period, BonusPlan.employee_id)).all()
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
    originals |= {v for v in db.scalars(select(UserManagedBg.bg).distinct()).all() if v}
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

def _latest_results_by_period(db: Session, bg: str | None, period: str | None,
                              year: str | None) -> list[tuple[str, "BonusResult"]]:
    """Latest result per (employee, plan_name) across ALL runs of a period.

    Scans every run of the period oldest→newest so a later run wins, but a person who
    was sealed (and therefore skipped by later recalculations) is still represented by
    the run that last computed them. Returns (period, result) pairs sorted by period.
    """
    from .models import BonusResult, CalcRun

    periods = db.scalars(select(CalcRun.period).distinct()).all()
    if period:
        periods = [p for p in periods if p == period]
    if year:
        periods = [p for p in periods if p.split("-")[0] == year]

    out: list[tuple[str, BonusResult]] = []
    for p in sorted(periods):
        runs = db.scalars(
            select(CalcRun).where(CalcRun.period == p)
            .order_by(CalcRun.created_at.asc(), CalcRun.id.asc())
        ).all()
        latest: dict[tuple[int, str], BonusResult] = {}
        for run in runs:
            for r in db.scalars(select(BonusResult).where(BonusResult.run_id == run.id)).all():
                latest[(r.employee_id, r.plan_name)] = r
        for (emp_id, plan_name), r in sorted(latest.items(), key=lambda kv: kv[0]):
            if not _bg_in(r.employee.bg, bg):
                continue
            out.append((p, r))
    return out


def export_results_rows(db: Session, bg: str | None = None, period: str | None = None,
                        year: str | None = None, lang: str = DEFAULT_LANG) -> list[list]:
    """One row per (person, plan) for the latest calculation that covers it.

    Weighted rates only (no unweighted rate is provided). Includes SEALED records —
    they are flagged with a `sealed` column instead of being dropped. Each row carries
    the employee's total weighted payout rate for that run; if the plan's KPI weights
    did not total 100% at calculation time, a comment is attached. Filterable by BG,
    exact period or year.
    """
    from .models import CalcRun

    t = Translator(lang)
    not_100_comment = t.t("weight_not_100_comment")
    header = ["period", "employee_id", "name", "bg", "department", "job_title", "plan_name",
              "weighted_rate_pct", "weight_total_pct", "adjustment_pct", "final_rate_pct",
              "adjusted", "sealed", "comment", "calculated_at"]
    rows = [header]
    for p, r in _latest_results_by_period(db, bg, period, year):
        emp = r.employee
        weight_total = r.weight_total_pct
        comment = "" if abs(weight_total - 100.0) < 1e-6 else not_100_comment
        sealed = "Y" if is_locked(db, p, emp.bg) else ""
        run = db.scalars(
            select(CalcRun).where(CalcRun.period == p, CalcRun.id == r.run_id)
        ).first()
        calculated_at = run.created_at.strftime("%Y-%m-%d %H:%M") if run else ""
        rows.append([p, emp.employee_id, emp.name, emp.bg, emp.department or "",
                     emp.job_title or "", r.plan_name,
                     f"{r.weighted_rate_pct:.2f}", fmt_num(weight_total),
                     f"{r.adjustment_pct:.2f}", f"{r.final_rate_pct:.2f}",
                     "Y" if r.adjusted else "", sealed, comment, calculated_at])
    return rows


def export_kpi_rows(db: Session, bg: str | None = None, period: str | None = None,
                    year: str | None = None, lang: str = DEFAULT_LANG) -> list[list]:
    """Per-KPI detail of the latest calculation covering each (person, plan).

    Companion to export_results_rows (which gives one total-rate row per plan).
    Exploded from BonusResult.detail_json captured at calculation time. Sealed records
    are included and flagged with a `sealed` column. Filterable by BG, period or year.
    """
    from .models import CalcRun

    header = ["period", "employee_id", "name", "bg", "department", "job_title", "plan_name",
              "kpi_name", "target", "actual", "curve_name", "weight_pct",
              "attainment_pct", "rate_pct", "weighted_contribution_pct", "sealed", "calculated_at"]
    rows = [header]
    for p, r in _latest_results_by_period(db, bg, period, year):
        emp = r.employee
        sealed = "Y" if is_locked(db, p, emp.bg) else ""
        run = db.scalars(
            select(CalcRun).where(CalcRun.period == p, CalcRun.id == r.run_id)
        ).first()
        calculated_at = run.created_at.strftime("%Y-%m-%d %H:%M") if run else ""
        try:
            detail = json.loads(r.detail_json) if r.detail_json else []
        except (ValueError, TypeError):
            detail = []
        for d in detail:
            actual = d.get("actual")
            rate = d.get("rate_pct") or 0.0
            weight = d.get("weight_pct") or 0.0
            contribution = round(weight / 100.0 * rate, 4)  # this KPI's weighted contribution
            rows.append([p, emp.employee_id, emp.name, emp.bg, emp.department or "",
                         emp.job_title or "", r.plan_name,
                         d.get("kpi", ""), fmt_num(d.get("quota")),
                         "" if actual is None else fmt_num(actual),
                         d.get("curve", ""), fmt_num(weight),
                         fmt_num(d.get("attainment_pct")), fmt_num(rate), fmt_num(contribution),
                         sealed, calculated_at])
    return rows


def to_csv(rows: list[list]) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()
