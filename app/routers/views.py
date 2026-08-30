"""Role-based views: employee self (4-quarter horizontal), multi-level manager team,
BG admin, person detail."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from ..csvio import export_results_rows, to_csv
from ..deps import get_db, require_roles, require_user
from ..i18n import Translator, get_lang
from ..models import BonusPlan, BonusResult, CalcRun, User
from ..ui import render

router = APIRouter()

MAX_MANAGER_DEPTH = 5  # managers can see up to +5 levels down


def all_periods(db) -> list[str]:
    periods = set(db.scalars(select(BonusPlan.period).distinct()).all())
    periods |= set(db.scalars(select(CalcRun.period).distinct()).all())
    return sorted(periods, reverse=True)


def latest_run(db, period: str) -> CalcRun | None:
    return db.scalars(
        select(CalcRun).where(CalcRun.period == period).order_by(CalcRun.created_at.desc(), CalcRun.id.desc())
    ).first()


def result_for(db, uid: int, period: str, plan_name: str | None = None) -> BonusResult | None:
    run = latest_run(db, period)
    if not run:
        return None
    stmt = select(BonusResult).where(BonusResult.run_id == run.id, BonusResult.employee_id == uid)
    if plan_name:
        stmt = stmt.where(BonusResult.plan_name == plan_name)
    return db.scalars(stmt).first()


def plan_for(db, uid: int, period: str, plan_name: str | None = None) -> BonusPlan | None:
    stmt = select(BonusPlan).where(
        BonusPlan.period == period, BonusPlan.employee_id == uid,
        BonusPlan.is_current == True, BonusPlan.is_deleted == False,  # noqa: E712
    )
    if plan_name:
        stmt = stmt.where(BonusPlan.plan_name == plan_name)
    return db.scalars(stmt).first()


# ---------------------------------------------------------------- multi-level hierarchy

def subtree(db, root_id: int, max_depth: int = MAX_MANAGER_DEPTH) -> list[tuple[User, int]]:
    """All active reports below root, as (user, depth). depth 1 = direct report (N-1)."""
    out: list[tuple[User, int]] = []
    frontier = [(root_id, 0)]
    seen = {root_id}
    while frontier:
        nxt = []
        for node_id, depth in frontier:
            if depth >= max_depth:
                continue
            children = db.scalars(
                select(User).where(User.manager_id == node_id, User.is_active == True)  # noqa: E712
            ).all()
            for child in children:
                if child.id in seen:
                    continue
                seen.add(child.id)
                out.append((child, depth + 1))
                nxt.append((child.id, depth + 1))
        frontier = nxt
    return out


def can_view(db, user: User, target: User) -> bool:
    if user.role == "ADMIN":
        return True
    if user.id == target.id:
        return True
    if user.role == "BG_ADMIN" and target.bg == user.bg:
        return True
    if user.role == "MANAGER":
        return any(u.id == target.id for u, _ in subtree(db, user.id))
    return False


@router.get("/")
def home(user: User = Depends(require_user)):
    from ..deps import home_for

    return RedirectResponse(home_for(user), status_code=303)


# ---------------------------------------------------------------- person / me (4-quarter)

def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _year_periods(year: int) -> list[str]:
    return [f"{year}-Q{i}" for i in (1, 2, 3, 4)]


def _year_plan_names(db, uid: int, year: int) -> list[str]:
    stmt = (
        select(BonusPlan.plan_name)
        .where(
            BonusPlan.employee_id == uid, BonusPlan.period.in_(_year_periods(year)),
            BonusPlan.is_current == True, BonusPlan.is_deleted == False,  # noqa: E712
        )
        .distinct()
    )
    return list(db.scalars(stmt).all())


def build_plan_table(db, uid: int, year: int, plan_name: str, tr: Translator) -> dict:
    """Build a metric-rows x 4-quarter-cols table for one plan (by plan_name)."""
    periods = _year_periods(year)
    qdata = []
    for period in periods:
        plan = plan_for(db, uid, period, plan_name)
        result = result_for(db, uid, period, plan_name)
        detail = {d["kpi"]: d for d in (json.loads(result.detail_json) if result else [])}
        qdata.append({"period": period, "plan": plan, "result": result, "detail": detail})

    kpi_names: list[str] = []
    for q in qdata:
        if q["plan"]:
            for k in q["plan"].kpis:
                if k.kpi_name not in kpi_names:
                    kpi_names.append(k.kpi_name)

    rows = []
    for kpi in kpi_names:
        target_cells, attain_cells, rate_cells = [], [], []
        for q in qdata:
            kpi_obj = next((k for k in q["plan"].kpis if k.kpi_name == kpi), None) if q["plan"] else None
            d = q["detail"].get(kpi)
            target_cells.append(_fmt(kpi_obj.quota) if kpi_obj else "")
            if d and d.get("actual") is not None:
                attain_cells.append(f"{d['attainment_pct']:g}%")
                rate_cells.append(f"{d['rate_pct']:g}%")
            else:
                attain_cells.append("")
                rate_cells.append("")
        kpi_label = tr.tl(kpi)
        rows.append({"label": f"{kpi_label} · {tr.t('target')}", "cells": target_cells, "kind": "target"})
        rows.append({"label": f"{kpi_label} · {tr.t('attainment')}", "cells": attain_cells, "kind": ""})
        rows.append({"label": f"{kpi_label} · {tr.t('payout_rate')}", "cells": rate_cells, "kind": ""})

    for key, kind in (("unweighted_rate", "unweighted"), ("weighted_rate", "weighted"),
                      ("special_adjust", "adj"), ("quarter_total_rate", "final")):
        cells = []
        for q in qdata:
            r = q["result"]
            if not r:
                cells.append("")
            elif kind == "unweighted":
                cells.append(f"{r.unweighted_rate_pct:g}%")
            elif kind == "weighted":
                cells.append(f"{r.weighted_rate_pct:g}%")
            elif kind == "adj":
                cells.append(f"{r.adjustment_pct:+g}%" if r.adjusted else "")
            else:
                cells.append(f"{r.final_rate_pct:g}%")
        rows.append({"label": tr.t(key), "cells": cells, "kind": "summary"})

    return {"plan_name": plan_name, "quarters": ["Q1", "Q2", "Q3", "Q4"], "rows": rows}


def _person_context(db, target: User, year: str | None, lang: str):
    data_years = sorted(
        {int(p.split("-")[0]) for p in db.scalars(
            select(BonusPlan.period).where(
                BonusPlan.employee_id == target.id, BonusPlan.is_current == True  # noqa: E712
            )).all()},
        reverse=True,
    )
    latest = data_years[0] if data_years else datetime.now().year
    selectable = [latest, latest - 1]  # only current + previous year selectable
    try:
        year_int = int(year) if year else latest
    except ValueError:
        year_int = latest
    if year_int not in selectable:
        year_int = latest
    tr = Translator(lang)
    plan_tables = [build_plan_table(db, target.id, year_int, name, tr)
                   for name in _year_plan_names(db, target.id, year_int)]
    return {
        "view_user": target,
        "years": selectable,
        "year": year_int,
        "plan_tables": plan_tables,
    }


@router.get("/me")
def me(request: Request, year: str | None = None, user: User = Depends(require_user), db=Depends(get_db)):
    ctx = _person_context(db, user, year, get_lang(request))
    return render(request, "person.html", user=user, **ctx)


@router.get("/person/{uid}")
def person(request: Request, uid: int, year: str | None = None,
           user: User = Depends(require_user), db=Depends(get_db)):
    target = db.get(User, uid)
    if not target or not can_view(db, user, target):
        return RedirectResponse("/", status_code=303)
    ctx = _person_context(db, target, year, get_lang(request))
    return render(request, "person.html", user=user, **ctx)


# ---------------------------------------------------------------- manager team (multi-level)

@router.get("/team")
def team(request: Request, period: str | None = None, level: str | None = None,
         sort: str | None = None, user: User = Depends(require_roles("MANAGER", "ADMIN")),
         db=Depends(get_db)):
    periods = all_periods(db)
    period = period or (periods[0] if periods else None)
    members = subtree(db, user.id)
    rows = []
    for emp, depth in members:
        r = result_for(db, emp.id, period) if period else None
        rows.append({"emp": emp, "result": r, "depth": depth, "level": f"N-{depth}"})

    all_levels = sorted({x["level"] for x in rows}, key=lambda s: int(s.split("-")[1]))

    if level:
        rows = [x for x in rows if x["level"] == level]

    sort = sort or "level"
    if sort == "name":
        rows.sort(key=lambda x: x["emp"].employee_id)
    elif sort == "rate":
        rows.sort(key=lambda x: (x["result"].final_rate_pct if x["result"] else -1), reverse=True)
    else:
        rows.sort(key=lambda x: (x["depth"], x["emp"].employee_id))

    counted = [x["result"].final_rate_pct for x in rows if x["result"]]
    avg_rate = round(sum(counted) / len(counted), 2) if counted else None
    return render(request, "team.html", user=user, rows=rows, periods=periods, period=period,
                  levels=all_levels, level=level or "", sort=sort, avg_rate=avg_rate)


# ---------------------------------------------------------------- BG view

@router.get("/bg")
def bg(request: Request, period: str | None = None,
       user: User = Depends(require_roles("BG_ADMIN", "ADMIN")), db=Depends(get_db)):
    periods = all_periods(db)
    period = period or (periods[0] if periods else None)
    members = db.scalars(
        select(User).where(User.bg == user.bg, User.role != "ADMIN").order_by(User.employee_id)
    ).all()
    rows, rates = [], []
    for emp in members:
        r = result_for(db, emp.id, period) if period else None
        if r:
            rates.append(r.final_rate_pct)
        rows.append({"emp": emp, "result": r})
    avg_rate = round(sum(rates) / len(rates), 2) if rates else None
    return render(request, "bg.html", user=user, rows=rows, periods=periods, period=period,
                  avg_rate=avg_rate)


@router.get("/bg/export.csv")
def bg_export(period: str | None = None, user: User = Depends(require_roles("BG_ADMIN", "ADMIN")),
              db=Depends(get_db)):
    rows = export_results_rows(db, bg=user.bg, period=period)
    name = f"bonus_history_{user.bg}" + (f"_{period}" if period else "") + ".csv"
    return Response(
        "\ufeff" + to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
