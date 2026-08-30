"""Bonus calculation engine: plan + YTD actuals + curves -> rates only.

Rates:
  unweighted = simple mean of per-KPI payout rates
  weighted   = sum(weight/100 * rate)
  final      = weighted + special adjustment delta
No bonus base is stored, so no payable amount is computed.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .curves import payout_rate
from .i18n import DEFAULT_LANG, Translator
from .models import Actual, Adjustment, BonusPlan, BonusResult, CalcRun, Lock, User


def is_locked(db: Session, period: str, bg: str | None) -> bool:
    if not bg:
        return False
    stmt = select(Lock.id).where(Lock.period == period, Lock.bg == bg)
    return db.scalar(stmt) is not None


def latest_adjustment(db: Session, employee_id: int, period: str) -> Adjustment | None:
    stmt = (
        select(Adjustment)
        .where(Adjustment.employee_id == employee_id, Adjustment.period == period)
        .order_by(Adjustment.created_at.desc(), Adjustment.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def current_actuals(db: Session, employee_id: int, period: str) -> dict[str, float]:
    """Latest (is_current) non-deleted actuals for an employee/period."""
    rows = db.scalars(
        select(Actual).where(
            Actual.period == period,
            Actual.employee_id == employee_id,
            Actual.is_current == True,  # noqa: E712
            Actual.is_deleted == False,  # noqa: E712
        )
    ).all()
    return {a.kpi_name: a.actual for a in rows}


def compute_plan(db: Session, plan: BonusPlan, period: str) -> dict:
    """Compute one plan's rates for an employee. Pure with respect to DB state."""
    actuals = current_actuals(db, plan.employee_id, period)
    detail = []
    weighted_rate = 0.0
    rate_sum = 0.0
    for kpi in plan.kpis:
        actual = actuals.get(kpi.kpi_name)
        attainment = (actual / kpi.quota * 100.0) if (actual is not None and kpi.quota) else 0.0
        rate = payout_rate(kpi.curve.points, attainment, kpi.curve.cap_pct)
        weighted_rate += kpi.weight_pct / 100.0 * rate
        rate_sum += rate
        detail.append(
            {
                "kpi": kpi.kpi_name,
                "quota": kpi.quota,
                "actual": actual,
                "curve": kpi.curve.name,
                "weight_pct": kpi.weight_pct,
                "attainment_pct": round(attainment, 2),
                "rate_pct": rate,
            }
        )
    n = len(plan.kpis)
    unweighted_rate = round(rate_sum / n, 4) if n else 0.0
    weighted_rate = round(weighted_rate, 4)
    adj = latest_adjustment(db, plan.employee_id, period)
    adjustment_pct = adj.adjustment_pct if adj else 0.0
    final_rate = round(weighted_rate + adjustment_pct, 4)
    return {
        "plan_name": plan.plan_name,
        "detail": detail,
        "unweighted_rate_pct": unweighted_rate,
        "weighted_rate_pct": weighted_rate,
        "adjustment_pct": adjustment_pct,
        "final_rate_pct": final_rate,
        "adjusted": adj is not None,
    }


def current_plans(db: Session, period: str, employee_ids: list[int] | None = None) -> list[BonusPlan]:
    stmt = select(BonusPlan).where(
        BonusPlan.period == period,
        BonusPlan.is_current == True,  # noqa: E712
        BonusPlan.is_deleted == False,  # noqa: E712
    )
    if employee_ids is not None:
        stmt = stmt.where(BonusPlan.employee_id.in_(employee_ids))
    return list(db.scalars(stmt).all())


def run_calculation(db: Session, period: str, admin: User, note: str = "",
                    employee_ids: list[int] | None = None, lang: str = DEFAULT_LANG) -> tuple[CalcRun, dict]:
    """Trigger a calculation run for a period. Sealed (period, bg) scopes are skipped."""
    plans = current_plans(db, period, employee_ids)
    if not plans:
        raise ValueError(Translator(lang).t("err_no_plans", period=period))
    locked_bgs = {bg for bg in db.scalars(select(Lock.bg).where(Lock.period == period)).all()}
    run = CalcRun(period=period, note=note, created_by=admin.id)
    db.add(run)
    db.flush()
    skipped = []
    for plan in plans:
        employee = plan.employee
        if employee.bg in locked_bgs:
            skipped.append(employee.employee_id)
            continue
        calc = compute_plan(db, plan, period)
        db.add(
            BonusResult(
                run_id=run.id,
                employee_id=plan.employee_id,
                period=period,
                plan_name=plan.plan_name,
                detail_json=json.dumps(calc["detail"], ensure_ascii=False),
                unweighted_rate_pct=calc["unweighted_rate_pct"],
                weighted_rate_pct=calc["weighted_rate_pct"],
                adjustment_pct=calc["adjustment_pct"],
                final_rate_pct=calc["final_rate_pct"],
                adjusted=calc["adjusted"],
            )
        )
    db.commit()
    return run, {"computed": len(plans) - len(skipped), "skipped": skipped}


def apply_adjustment(db: Session, employee_id: int, period: str, adjustment_pct: float,
                     reason: str, admin: User, lang: str = DEFAULT_LANG) -> Adjustment:
    """Record a special adjustment (delta) and refresh the latest run's results for it."""
    employee = db.get(User, employee_id)
    if is_locked(db, period, employee.bg if employee else None):
        raise ValueError(Translator(lang).t("err_sealed"))
    adj = Adjustment(
        employee_id=employee_id, period=period, adjustment_pct=adjustment_pct,
        reason=reason, created_by=admin.id,
    )
    db.add(adj)
    db.flush()
    # refresh this employee's results in the latest run of the period
    run = db.scalars(
        select(CalcRun).where(CalcRun.period == period)
        .order_by(CalcRun.created_at.desc(), CalcRun.id.desc())
    ).first()
    if run:
        plans = {p.plan_name: p for p in current_plans(db, period, [employee_id])}
        results = db.scalars(
            select(BonusResult).where(BonusResult.run_id == run.id, BonusResult.employee_id == employee_id)
        ).all()
        for result in results:
            plan = plans.get(result.plan_name)
            if not plan:
                continue
            calc = compute_plan(db, plan, period)
            result.unweighted_rate_pct = calc["unweighted_rate_pct"]
            result.weighted_rate_pct = calc["weighted_rate_pct"]
            result.adjustment_pct = calc["adjustment_pct"]
            result.final_rate_pct = calc["final_rate_pct"]
            result.adjusted = calc["adjusted"]
    db.commit()
    return adj
